"""统一的回测报告构造器。

把策略对象、初始/最终资金、交易记录与已经算好的 metrics 打包成一个
JSON 可序列化的 dict（保持与 1.0 输出格式一致）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..strategies.base import TradeRecord


def _trade_to_dict(t: TradeRecord) -> Dict[str, Any]:
    return {
        "date": t.date.strftime("%Y-%m-%d %H:%M:%S"),
        "action": t.action,
        "price": t.price,
        "size": t.size,
        "value": t.value,
        "commission": t.commission,
        "pnl": t.pnl,
        "total_value": t.total_value,
        "signal_reason": t.signal_reason,
        "cash": t.cash,
    }


def build_report(
    strat,
    initial_capital: float,
    final_value: float,
    trade_records: List[TradeRecord],
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """生成单次回测的标准报告。"""
    total_return = ((final_value / initial_capital) - 1) * 100
    next_signal = strat._predict_next_signal()

    all_trades = [_trade_to_dict(t) for t in trade_records]
    recent_trades = all_trades[-20:] if all_trades else []

    return {
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_return": total_return,
        "metrics": metrics,
        "all_trades": all_trades,
        "trades": recent_trades,
        "next_signal": next_signal,
        "last_trade_date": strat.data.datetime.datetime(),
    }


def trade_record_to_dict(t: TradeRecord) -> Dict[str, Any]:
    """对外暴露的转换辅助。"""
    return _trade_to_dict(t)
