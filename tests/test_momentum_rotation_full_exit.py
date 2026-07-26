"""MomentumTopNStrategy 完全清仓时的份额精度回归测试（端到端，真跑 backtrader）。

历史 bug：清仓卖出份额用"目标市值 ÷ 当前价"反推，浮点往返误差偶尔比实际
持仓少 1 股，留下的尾差会被 _build_rotations 的 FIFO 重建误配对到后续
无关的一次卖出上，产出重叠的持仓段（详见 test_rotation_export.py）。
这里端到端验证：真实 Top-1 动量轮动跑几轮切换后，导出的 rotations 不重叠。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import backtrader as bt

from trading.analysis.report import trade_record_to_dict
from trading.engine.single import _attach_analyzers, _make_data_feed
from trading.io.rotation_export import _build_rotations
from trading.strategies.momentum import Schedule, resolve_momentum_fn
from trading.strategies.momentum_rotation import (
    MomentumTopNStrategy,
    _MomentumStrategyMixinState,
)


def _build_df(closes):
    dates = pd.bdate_range(start="2022-01-03", periods=len(closes))
    return pd.DataFrame(
        {
            "date": dates,
            "open_price": closes,
            "close_price": closes,
            "high": closes * 1.001,
            "low": closes * 0.999,
            "volume": 1_000_000,
        }
    )


def _run_rotation_backtest():
    # 三段明显的动量切换 (A 强 -> B 强 -> C 强 -> A 强)，逼着策略多次完全清仓、
    # 重新建仓——正是历史 bug 出现的场景。
    closes_a = np.concatenate(
        [np.linspace(100, 140, 80), np.linspace(140, 130, 60),
         np.linspace(130, 150, 60), np.linspace(150, 190, 60)]
    )
    closes_b = np.concatenate(
        [np.linspace(100, 105, 80), np.linspace(105, 160, 60),
         np.linspace(160, 150, 60), np.linspace(150, 140, 60)]
    )
    closes_c = np.concatenate(
        [np.linspace(100, 95, 80), np.linspace(95, 90, 60),
         np.linspace(90, 150, 60), np.linspace(150, 130, 60)]
    )

    cerebro = bt.Cerebro()
    for symbol, closes in (("SYM_A", closes_a), ("SYM_B", closes_b), ("SYM_C", closes_c)):
        feed = _make_data_feed(_build_df(closes))
        feed._name = symbol
        cerebro.adddata(feed, name=symbol)

    cerebro.broker.setcash(50_000)
    cerebro.broker.setcommission(commission=0.0001)

    state = _MomentumStrategyMixinState(
        momentum_fn=resolve_momentum_fn("simple_return"),
        schedule=Schedule.every_n_trading_days(1),
        lookback=20,
        threshold=-0.99,
        cooldown_days=0,
        top_n=1,
        cash_buffer=0.05,
    )
    cerebro.addstrategy(MomentumTopNStrategy, state=state)
    _attach_analyzers(cerebro)

    strat = cerebro.run()[0]
    return [trade_record_to_dict(t) for t in strat.trade_records]


def _with_symbol(trades):
    out = []
    for t in trades:
        reason = t.get("signal_reason", "")
        symbol = reason.rsplit("[", 1)[-1][:-1] if "[" in reason and reason.endswith("]") else ""
        out.append({**t, "symbol": symbol})
    return out


class TestFullExitDoesNotLeaveDust:
    def test_rotation_backtest_produces_no_overlapping_segments(self):
        trades = _with_symbol(_run_rotation_backtest())
        assert len(trades) > 0

        # 不应该抛 OverlappingRotationsError——这就是端到端的验收标准
        rotations = _build_rotations(trades)
        assert len(rotations) > 0

    def test_every_full_exit_sell_clears_the_entire_lot(self):
        """更直接的断言：每次完全清仓的 SELL，卖出份额必须等于此前对应
        BUY 的份额（不多不少），而不是 BUY 之后累计持仓量的近似值。"""
        trades = _with_symbol(_run_rotation_backtest())
        by_symbol = {}
        for t in trades:
            by_symbol.setdefault(t["symbol"], []).append(t)

        for symbol, symbol_trades in by_symbol.items():
            symbol_trades.sort(key=lambda t: t["date"])
            open_size = 0
            for t in symbol_trades:
                if t["action"] == "BUY":
                    open_size += t["size"]
                else:
                    assert t["size"] == open_size, (
                        f"{symbol} 在 {t['date']} 的清仓卖出只卖了 {t['size']}，"
                        f"实际持仓是 {open_size}，留下了尾差"
                    )
                    open_size = 0
