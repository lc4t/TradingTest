"""_build_rotations / 重叠校验的回归测试。

覆盖的历史 bug：完全清仓时用"目标市值 ÷ 当前价"反推卖出份额，浮点往返误差
偶尔比实际持仓少 1 股，卖不干净的尾差会一直挂在 FIFO 队列里，被后续任意一次
无关的卖出误配对，导致 entryDate 被错误地拉回很久以前，产出重叠的持仓段。
"""
from __future__ import annotations

import pytest

from trading.io.rotation_export import (
    OverlappingRotationsError,
    _build_rotations,
)


def make_trade(date: str, action: str, symbol: str, price: float, size: int, pnl: float = 0.0):
    return {
        "date": date,
        "action": action,
        "symbol": symbol,
        "price": price,
        "size": size,
        "pnl": pnl,
    }


class TestBuildRotationsCleanCase:
    def test_single_clean_round_trip(self):
        trades = [
            make_trade("2023-02-09 00:00:00", "BUY", "513100.SS", 0.871, 61822),
            make_trade("2023-02-10 00:00:00", "SELL", "513100.SS", 0.863, 61822),
        ]
        rotations = _build_rotations(trades)
        assert len(rotations) == 1
        assert rotations[0]["entryDate"] == "2023-02-09 00:00:00"
        assert rotations[0]["exitDate"] == "2023-02-10 00:00:00"

    def test_multiple_sequential_round_trips_do_not_overlap(self):
        trades = [
            make_trade("2023-02-09 00:00:00", "BUY", "513100.SS", 0.871, 61822),
            make_trade("2023-02-10 00:00:00", "SELL", "513100.SS", 0.863, 61822),
            make_trade("2023-02-15 00:00:00", "BUY", "513100.SS", 0.875, 61903),
            make_trade("2023-03-10 00:00:00", "SELL", "513100.SS", 0.851, 61903),
        ]
        rotations = _build_rotations(trades)
        assert len(rotations) == 2
        assert rotations[1]["entryDate"] == "2023-02-15 00:00:00"


class TestBuildRotationsDustBugRegression:
    def test_leftover_share_from_incomplete_sell_raises_on_next_unrelated_cycle(self):
        """完整还原 513100.SS 报告里那组"02-15 建仓，分别持有到 03-10 和 03-29"。"""
        trades = [
            make_trade("2023-02-15 00:00:00", "BUY", "513100.SS", 0.875, 61903),
            # 卖出比实际持仓少 1 股（浮点尾差），留下 1 股挂在队列里
            make_trade("2023-03-10 00:00:00", "SELL", "513100.SS", 0.851, 61902),
            # 完全独立的一次新建仓
            make_trade("2023-03-28 00:00:00", "BUY", "513100.SS", 0.891, 60945),
            # 这次卖出会先"捡"到上次的 1 股尾差，导致 entryDate 被污染成 02-15
            make_trade("2023-03-29 00:00:00", "SELL", "513100.SS", 0.890, 60946),
        ]
        with pytest.raises(OverlappingRotationsError, match="513100.SS"):
            _build_rotations(trades)

    def test_no_dust_no_overlap(self):
        """同样的两轮买卖，但卖出份额和买入完全对齐（没有尾差）——不应报错。"""
        trades = [
            make_trade("2023-02-15 00:00:00", "BUY", "513100.SS", 0.875, 61903),
            make_trade("2023-03-10 00:00:00", "SELL", "513100.SS", 0.851, 61903),
            make_trade("2023-03-28 00:00:00", "BUY", "513100.SS", 0.891, 60945),
            make_trade("2023-03-29 00:00:00", "SELL", "513100.SS", 0.890, 60945),
        ]
        rotations = _build_rotations(trades)
        assert len(rotations) == 2
        assert [r["entryDate"] for r in rotations] == [
            "2023-02-15 00:00:00",
            "2023-03-28 00:00:00",
        ]

    def test_different_symbols_do_not_interfere(self):
        trades = [
            make_trade("2023-02-15 00:00:00", "BUY", "513100.SS", 0.875, 1000),
            make_trade("2023-03-10 00:00:00", "SELL", "513100.SS", 0.851, 1000),
            make_trade("2023-02-20 00:00:00", "BUY", "518880.SS", 5.0, 500),
            make_trade("2023-03-15 00:00:00", "SELL", "518880.SS", 5.2, 500),
        ]
        rotations = _build_rotations(trades)
        assert len(rotations) == 2
