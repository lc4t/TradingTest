"""动量轮动策略：

- :class:`MomentumBasketStrategy` —— 用户为每个候选预设目标权重，动量 ≥ 阈值时
  保留权重，否则转现金。
- :class:`MomentumTopNStrategy` —— 每期取动量最强的 N 个，等权持有，可选现金 buffer。

两个策略共享调仓日历 :class:`Schedule`、冷却期与执行延迟参数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import backtrader as bt
from loguru import logger

from .base import TradeRecord
from .momentum import MomentumFn, Schedule, resolve_momentum_fn


def _floor_int(x: float) -> int:
    """容错地把 size 转成非负整数。"""
    return max(0, int(x))


def _record_order(strategy, order, signal_reason: str) -> Optional[TradeRecord]:
    """生成 TradeRecord (买入或卖出)。"""
    if order.status not in (order.Completed,):
        return None
    size = abs(order.executed.size)
    price = order.executed.price
    value = price * size
    commission = order.executed.comm
    cash_after = strategy.broker.get_cash()
    portfolio_value = strategy.broker.getvalue()
    if order.isbuy():
        pnl = 0.0
        action = "BUY"
    else:
        pnl = order.executed.pnl - commission
        action = "SELL"

    return TradeRecord(
        date=strategy.datas[0].datetime.datetime(),
        action=action,
        price=price,
        size=size,
        value=value,
        commission=commission,
        pnl=pnl,
        total_value=portfolio_value,
        signal_reason=signal_reason,
        cash=cash_after,
    )


@dataclass
class _MomentumStrategyMixinState:
    """非 backtrader 的状态，包装一下避免 params 系统的限制。"""

    momentum_fn: MomentumFn
    schedule: Schedule
    lookback: int
    threshold: float
    cooldown_days: int
    target_weights: Dict[str, float] = field(default_factory=dict)
    top_n: Optional[int] = None
    cash_buffer: float = 0.0
    last_signal_reason: str = ""
    cooldown_remaining: int = 0


class _MomentumBaseStrategy(bt.Strategy):
    """两套动量策略的共享实现。"""

    params = (
        ("state", None),  # _MomentumStrategyMixinState 实例
    )

    def __init__(self):
        self._state: _MomentumStrategyMixinState = self.params.state
        if self._state is None:
            raise ValueError("必须通过 cerebro.addstrategy(..., state=...) 注入 state")
        self._state.schedule.reset()
        self._state.cooldown_remaining = 0

        # data feed name -> data feed 对象
        self._feed_by_name: Dict[str, bt.DataBase] = {
            d._name: d for d in self.datas
        }
        self._pending_orders: List = []
        self._last_signal_reasons: Dict[str, str] = {}
        self.trade_records: List[TradeRecord] = []

    # ------------------------------------------------------------------
    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        symbol = order.data._name if order.data is not None else "?"
        reason = self._last_signal_reasons.pop(id(order), "动量轮动")
        if order.status == order.Completed:
            rec = _record_order(self, order, signal_reason=f"{reason} [{symbol}]")
            if rec is not None:
                self.trade_records.append(rec)
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            logger.warning(
                f"Order failed: {symbol} status={order.getstatusname()} "
                f"size={order.size}"
            )

    # ------------------------------------------------------------------
    def _closes(self, data) -> List[float]:
        """取出当前可用的全部收盘价（升序）。"""
        # 防止 lookback 越界，最多取已经填好的窗口
        avail = len(data)
        if avail == 0:
            return []
        # data.close 是 backtrader 的 line，逆向索引：data.close[0] 是最新
        return [data.close[-(avail - 1 - i)] for i in range(avail)]

    def _compute_momentum(self, data) -> float:
        closes = self._closes(data)
        return self._state.momentum_fn(closes, self._state.lookback)

    # ------------------------------------------------------------------
    def _target_weights(self) -> Dict[str, float]:
        """返回 {symbol: 目标权重}，子类实现。"""
        raise NotImplementedError

    def _signal_reason(self, momentums: Dict[str, float]) -> str:
        parts = [f"{s}: {m:.4f}" if not (m != m) else f"{s}: NaN" for s, m in momentums.items()]
        return "[动量] " + ", ".join(parts)

    # ------------------------------------------------------------------
    def next(self):
        today = self.datas[0].datetime.date(0)

        # 计算 schedule（必须每天都 call 维护状态）
        fire = self._state.schedule.should_fire(today)
        if self._state.cooldown_remaining > 0:
            self._state.cooldown_remaining -= 1
        if not fire:
            return
        if self._state.cooldown_remaining > 0:
            return

        # 触发 rebalance
        momentums: Dict[str, float] = {}
        for name, feed in self._feed_by_name.items():
            momentums[name] = self._compute_momentum(feed)

        targets = self._compute_targets(momentums)
        reason = self._signal_reason(momentums)

        # 调仓: 简化为按目标比例直接重新分配
        portfolio_value = self.broker.getvalue()
        for name, feed in self._feed_by_name.items():
            target_weight = targets.get(name, 0.0)
            target_value = portfolio_value * target_weight
            current_size = self.getposition(feed).size
            current_value = current_size * feed.close[0]
            delta_value = target_value - current_value

            if abs(delta_value) < feed.close[0]:  # 一手都不到，跳过
                continue

            if delta_value > 0:
                size_delta = _floor_int(delta_value / feed.close[0])
                if size_delta <= 0:
                    continue
                order = self.buy(data=feed, size=size_delta)
                self._last_signal_reasons[id(order)] = reason
            else:
                size_delta = _floor_int(-delta_value / feed.close[0])
                size_delta = min(size_delta, current_size)
                if size_delta <= 0:
                    continue
                order = self.sell(data=feed, size=size_delta)
                self._last_signal_reasons[id(order)] = reason

        # 冷却期：N 个交易日内不再 fire
        self._state.cooldown_remaining = self._state.cooldown_days

    # ------------------------------------------------------------------
    def _compute_targets(self, momentums: Dict[str, float]) -> Dict[str, float]:
        """子类实现：把动量字典映射成 {symbol: target_weight}."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    def _predict_next_signal(self) -> Dict:
        """供 build_report 调用，输出当前持仓 + 下次预期调仓动作。"""
        today = self.datas[0].datetime.date(0)
        momentums = {
            name: self._compute_momentum(feed) for name, feed in self._feed_by_name.items()
        }
        targets = self._compute_targets(momentums)

        positions = {}
        for name, feed in self._feed_by_name.items():
            pos = self.getposition(feed)
            positions[name] = {
                "size": pos.size,
                "price": feed.close[0],
                "value": pos.size * feed.close[0],
                "momentum": momentums[name],
                "target_weight": targets.get(name, 0.0),
            }

        return {
            "action": "调仓" if any(targets.values()) else "持币",
            "conditions": [f"{s}: momentum={m:.4f}" for s, m in momentums.items()],
            "timestamp": today.strftime("%Y-%m-%d"),
            "prices": {n: p["price"] for n, p in positions.items()},
            "positions": positions,
            "target_weights": targets,
            "stop_loss": None,
            "position_info": None,
        }


class MomentumBasketStrategy(_MomentumBaseStrategy):
    """加权篮子策略：每个候选预设权重，动量 < 阈值时该标的转现金。"""

    def _compute_targets(self, momentums: Dict[str, float]) -> Dict[str, float]:
        targets: Dict[str, float] = {}
        for sym, weight in self._state.target_weights.items():
            m = momentums.get(sym, float("nan"))
            if m != m:  # NaN
                targets[sym] = 0.0
                continue
            if m >= self._state.threshold:
                targets[sym] = weight
            else:
                targets[sym] = 0.0
        return targets


class MomentumTopNStrategy(_MomentumBaseStrategy):
    """Top-N 等权策略：每期取动量最高的 N 个标的等权持有。"""

    def _compute_targets(self, momentums: Dict[str, float]) -> Dict[str, float]:
        candidates = [
            (sym, m)
            for sym, m in momentums.items()
            if m == m and m >= self._state.threshold
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)
        top = candidates[: (self._state.top_n or 1)]
        if not top:
            return {sym: 0.0 for sym in momentums}

        investable = 1.0 - self._state.cash_buffer
        each = investable / len(top)
        targets = {sym: 0.0 for sym in momentums}
        for sym, _ in top:
            targets[sym] = each
        return targets
