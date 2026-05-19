"""把动量轮动的回测结果序列化成前端 `/rotation/[strategy]` 可消费的 JSON。

Schema version: ``rotation-v1`` (与 1.0 单标的 schema 完全独立)。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from ..data.repository import DBClient
from ..engine.multi import MultiBacktestResult
from .json_export import get_stock_name


SCHEMA_VERSION = "rotation-v1"


def _date_str(v) -> str:
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _build_rotations(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从交易流水重建"持仓段"。

    每段持仓 = 一次 BUY 到对应 SELL（同一标的，按 FIFO 配对）。
    返回的每条记录是一次完整持仓的开始/结束/收益。
    """
    open_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    rotations: List[Dict[str, Any]] = []

    for t in sorted(trades, key=lambda x: x["date"]):
        symbol = t.get("symbol") or _symbol_from_reason(t.get("signal_reason", ""))
        if t["action"] == "BUY":
            open_by_symbol.setdefault(symbol, []).append(
                {
                    "buy_date": t["date"],
                    "buy_price": t["price"],
                    "buy_size": t["size"],
                    "remaining": t["size"],
                }
            )
        elif t["action"] == "SELL":
            queue = open_by_symbol.get(symbol, [])
            size_left = t["size"]
            total_cost = 0.0
            buy_dates: List[str] = []
            while queue and size_left > 0:
                head = queue[0]
                used = min(size_left, head["remaining"])
                total_cost += used * head["buy_price"]
                buy_dates.append(head["buy_date"])
                head["remaining"] -= used
                size_left -= used
                if head["remaining"] <= 0:
                    queue.pop(0)
            if t["size"] > 0:
                avg_entry = total_cost / t["size"]
                period_return_pct = (t["price"] / avg_entry - 1) * 100 if avg_entry else 0.0
                # holding_days：取最早匹配的 buy_date
                start_date = buy_dates[0] if buy_dates else t["date"]
                holding_days = _date_diff(start_date, t["date"])
                rotations.append(
                    {
                        "symbol": symbol,
                        "entryDate": _date_str(start_date),
                        "exitDate": _date_str(t["date"]),
                        "entryPrice": round(avg_entry, 4),
                        "exitPrice": round(t["price"], 4),
                        "size": t["size"],
                        "holdingDays": holding_days,
                        "periodReturnPct": round(period_return_pct, 3),
                        "pnl": round(t.get("pnl", 0.0), 2),
                    }
                )
    return rotations


def _date_diff(start: str, end: str) -> int:
    try:
        s = datetime.fromisoformat(str(start)[:19])
        e = datetime.fromisoformat(str(end)[:19])
        return (e - s).days
    except Exception:
        return 0


def _symbol_from_reason(reason: str) -> str:
    """从 signal_reason 末尾的 ``[SYMBOL]`` 提出 symbol。"""
    if "[" in reason and reason.endswith("]"):
        return reason.rsplit("[", 1)[-1][:-1]
    return ""


def _current_holding(
    rotations: List[Dict[str, Any]],
    last_buy: Optional[Dict[str, Any]],
    latest_prices: Dict[str, float],
    name_lookup: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """根据交易流水推断当前持仓。"""
    if not last_buy:
        return None
    symbol = last_buy["symbol"]
    entry_price = last_buy["price"]
    size = last_buy["size"]
    current_price = latest_prices.get(symbol, entry_price)
    market_value = current_price * size
    unrealized_pnl = (current_price - entry_price) * size
    unrealized_pnl_pct = ((current_price / entry_price) - 1) * 100 if entry_price else 0.0
    return {
        "symbol": symbol,
        "name": name_lookup.get(symbol, symbol),
        "since": _date_str(last_buy["date"]),
        "entryPrice": round(entry_price, 4),
        "currentPrice": round(current_price, 4),
        "size": size,
        "marketValue": round(market_value, 2),
        "unrealizedPnl": round(unrealized_pnl, 2),
        "unrealizedPnlPct": round(unrealized_pnl_pct, 3),
    }


def _next_signal_for_frontend(
    next_signal: Dict[str, Any],
    current_symbol: Optional[str],
) -> Dict[str, Any]:
    """把策略输出的 next_signal 翻译成 frontend 的 action 枚举."""
    targets: Dict[str, float] = next_signal.get("target_weights", {}) or {}
    selected = [s for s, w in targets.items() if w > 0]
    momentums = next_signal.get("positions") or {}
    if not selected:
        return {
            "action": "EXIT",
            "reason": "所有标的动量都低于阈值或为 NaN，下次预期空仓",
            "rotateFrom": current_symbol,
            "rotateTo": None,
            "evaluatedAt": next_signal.get("timestamp"),
        }
    next_target = selected[0]  # Top-1
    if current_symbol == next_target:
        return {
            "action": "HOLD",
            "reason": f"动量最强仍为 {next_target}",
            "rotateFrom": current_symbol,
            "rotateTo": next_target,
            "evaluatedAt": next_signal.get("timestamp"),
        }
    return {
        "action": "ROTATE",
        "reason": (
            f"下次预期换股: {current_symbol or '空仓'} → {next_target}"
        ),
        "rotateFrom": current_symbol,
        "rotateTo": next_target,
        "evaluatedAt": next_signal.get("timestamp"),
    }


def _universe_ranking(
    next_signal: Dict[str, Any],
    name_lookup: Dict[str, str],
) -> List[Dict[str, Any]]:
    """按动量降序输出 universe 排名."""
    positions = next_signal.get("positions") or {}
    targets = next_signal.get("target_weights") or {}
    ranked = sorted(
        positions.items(),
        key=lambda kv: (kv[1]["momentum"] if kv[1]["momentum"] == kv[1]["momentum"] else -1e18),
        reverse=True,
    )
    out = []
    for rank, (sym, info) in enumerate(ranked, start=1):
        out.append(
            {
                "symbol": sym,
                "name": name_lookup.get(sym, sym),
                "momentum": round(info["momentum"], 4) if info["momentum"] == info["momentum"] else None,
                "currentPrice": round(info["price"], 4),
                "targetWeight": round(targets.get(sym, 0.0), 3),
                "selected": targets.get(sym, 0.0) > 0,
                "rank": rank,
            }
        )
    return out


def _key_metrics(metrics: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """复用 1.0 的几个分组，结构对齐前端期望."""
    return {
        "returnMetrics": [
            {"name": "年化收益率", "value": round(metrics.get("annual_return", 0), 2),
             "description": "将总收益按年度平均"},
            {"name": "复合年化收益", "value": round(metrics.get("cagr", 0), 2),
             "description": "考虑再投资的年化"},
            {"name": "总盈亏", "value": round(metrics.get("total_pnl", 0), 2),
             "description": "所有交易的累计盈亏"},
        ],
        "riskMetrics": [
            {"name": "最大回撤", "value": round(metrics.get("max_drawdown", 0), 2),
             "description": "任意区间最大跌幅"},
            {"name": "当前回撤", "value": round(metrics.get("current_drawdown", 0), 2),
             "description": "距离历史峰值的跌幅"},
            {"name": "波动率", "value": round(metrics.get("volatility", 0), 2),
             "description": "收益率年化标准差"},
        ],
        "riskAdjustedMetrics": [
            {"name": "夏普比率", "value": round(metrics.get("sharpe_ratio", 0), 2),
             "description": ">1 较好，>2 优秀"},
            {"name": "Calmar比率", "value": round(metrics.get("calmar_ratio", 0), 2),
             "description": "年化收益 / 最大回撤"},
            {"name": "索提诺比率", "value": round(metrics.get("sortino_ratio", 0), 2),
             "description": "类似夏普，只考虑下行波动"},
        ],
        "tradingMetrics": [
            {"name": "总交易次数", "value": metrics.get("total_trades", 0)},
            {"name": "胜率", "value": round(metrics.get("win_rate", 0), 2)},
            {"name": "盈亏比", "value": round(metrics.get("profit_factor", 0), 2)},
            {"name": "平均盈利", "value": round(metrics.get("avg_won", 0), 2)},
            {"name": "平均亏损", "value": round(metrics.get("avg_lost", 0), 2)},
        ],
    }


def format_rotation_for_json(
    result: MultiBacktestResult,
    strategy_id: str,
    strategy_name: str,
    config: Dict[str, Any],
    db_client: Optional[DBClient] = None,
) -> Dict[str, Any]:
    """组装一份完整的 rotation-v1 JSON.

    Parameters
    ----------
    result:
        :class:`MultiBacktestResult`
    strategy_id:
        URL slug，用于 ``/rotation/<id>`` 路由，比如 ``"momentum-top1"``
    strategy_name:
        显示名称
    config:
        用于展示的策略参数（dict, 已经序列化好的 primitives）
    """
    universe = result.universe
    name_lookup: Dict[str, str] = {}
    if db_client is not None:
        for sym in universe:
            name_lookup[sym] = get_stock_name(db_client, sym)
    else:
        # 没有 DB 时，name = symbol
        for sym in universe:
            name_lookup[sym] = sym

    trades_with_symbol = []
    for t in result.trades:
        symbol = _symbol_from_reason(t.get("signal_reason", ""))
        trades_with_symbol.append({**t, "symbol": symbol})

    rotations = _build_rotations(trades_with_symbol)

    last_buys = [t for t in trades_with_symbol if t["action"] == "BUY"]
    last_buy = last_buys[-1] if last_buys else None
    # 推断 last buy 是否已经全部被 SELL 掉了：通过对应 symbol 的累计 buy - sell size
    held_size: Dict[str, int] = {}
    for t in trades_with_symbol:
        s = t.get("symbol") or ""
        if t["action"] == "BUY":
            held_size[s] = held_size.get(s, 0) + t["size"]
        else:
            held_size[s] = held_size.get(s, 0) - t["size"]
    current_symbol = None
    for s, sz in held_size.items():
        if sz > 0:
            current_symbol = s
            break

    latest_prices = {
        sym: info["price"]
        for sym, info in (result.next_signal.get("positions") or {}).items()
    }

    current_holding = None
    if current_symbol:
        # 找到该 symbol 最后一次 BUY 用作 entry
        relevant_buy = next(
            (t for t in reversed(trades_with_symbol) if t["symbol"] == current_symbol and t["action"] == "BUY"),
            None,
        )
        if relevant_buy:
            current_holding = _current_holding(
                rotations, relevant_buy, latest_prices, name_lookup
            )

    next_signal_payload = _next_signal_for_frontend(result.next_signal, current_symbol)
    universe_ranking = _universe_ranking(result.next_signal, name_lookup)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "strategyId": strategy_id,
        "strategyName": strategy_name,
        "reportDate": datetime.now().strftime("%Y-%m-%d"),
        "config": config,
        "dateRange": {
            "start": _date_str(result.start_date),
            "end": _date_str(result.end_date),
        },
        "summary": {
            "initialCapital": result.initial_capital,
            "finalValue": round(result.final_value, 2),
            "totalReturnPct": round(result.total_return_pct, 2),
            "annualReturn": round(result.metrics.get("annual_return", 0), 2),
            "maxDrawdown": round(result.metrics.get("max_drawdown", 0), 2),
            "sharpe": round(result.metrics.get("sharpe_ratio", 0), 2),
            "volatility": round(result.metrics.get("volatility", 0), 2),
        },
        "currentHolding": current_holding,
        "nextSignal": next_signal_payload,
        "universeRanking": universe_ranking,
        "rotations": rotations,
        "annualReturns": [
            {"year": int(y), "value": round(v, 3)}
            for y, v in (result.metrics.get("yearly_returns") or {}).items()
        ],
        "metrics": _key_metrics(result.metrics),
    }
