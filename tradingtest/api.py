"""用户态门面：在 Notebook / REPL / 脚本里只需要 import 这一个模块.

>>> from tradingtest.api import run_backtest, MomentumBasket
>>> result = run_backtest(
...     strategy=MomentumBasket(
...         weights={"159915.SZ": 0.4, "513100.SH": 0.4, "518880.SH": 0.2},
...     ),
...     start="2022-01-01",
...     initial_capital=50_000,
... )
>>> result.metrics
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd

from .data.repository import DBClient
from .engine.multi import MultiBacktestEngine, MultiBacktestResult
from .strategies.momentum import (
    MOMENTUM_FUNCTIONS,
    MomentumFn,
    Schedule,
    resolve_momentum_fn,
)
from .strategies.momentum_rotation import (
    MomentumBasketStrategy,
    MomentumTopNStrategy,
    _MomentumStrategyMixinState,
)


# ---------------------------------------------------------------------------
# 用户写的策略 spec（值对象，不是 backtrader 类本身）
# ---------------------------------------------------------------------------


@dataclass
class MomentumBasket:
    """动量加权篮子策略.

    Parameters
    ----------
    weights:
        ``{symbol: 目标权重}``。所有权重之和必须 ≤ 1.0，未占满的部分自动留作现金底仓。
    momentum_fn:
        动量算法 key 或自定义可调用对象。可选 key:
        ``simple_return`` / ``log_return`` / ``sharpe`` / ``weighted`` / ``dual_12_1``。
        默认 ``simple_return``。
    lookback:
        回望窗口（交易日）。默认 63（约 3 个月）。
    threshold:
        动量准入门槛。当某标的动量 < threshold 时，把它的目标权重转为现金。
        默认 -0.99（极宽，几乎不过滤）；调成 0 即 "不买入下跌标的"。
    schedule:
        调仓日历，默认 :func:`Schedule.every_n_trading_days(1)`。
    cooldown_days:
        触发一次 rebalance 后强制等待 N 个交易日。默认 0（无冷却）。
    """

    weights: Dict[str, float]
    momentum_fn: Union[str, MomentumFn] = "simple_return"
    lookback: int = 63
    threshold: float = -0.99
    schedule: Schedule = field(default_factory=lambda: Schedule.every_n_trading_days(1))
    cooldown_days: int = 0
    trend_filter_ma: Optional[int] = None  # 只在收盘价 > N 日均线时才持有

    def _validate(self) -> None:
        if not self.weights:
            raise ValueError("weights 不能为空")
        total = sum(self.weights.values())
        if total > 1.0 + 1e-9:
            raise ValueError(f"weights 之和 = {total:.4f} 超过 1.0")
        for sym, w in self.weights.items():
            if w < 0:
                raise ValueError(f"{sym} 的权重不能为负 (={w})")

    def _build_state(self) -> _MomentumStrategyMixinState:
        self._validate()
        return _MomentumStrategyMixinState(
            momentum_fn=resolve_momentum_fn(self.momentum_fn),
            schedule=self.schedule,
            lookback=self.lookback,
            threshold=self.threshold,
            cooldown_days=self.cooldown_days,
            target_weights=dict(self.weights),
            trend_ma=self.trend_filter_ma,
        )

    def _universe(self) -> List[str]:
        return list(self.weights)


@dataclass
class MomentumTopN:
    """Top-N 等权轮动策略.

    Parameters
    ----------
    universe:
        候选标的列表。
    top_n:
        每期持有的标的数。默认 1（独持最强）。
    cash_buffer:
        固定保留的现金比例（0..1）。默认 0，即满仓选中的 top_n 个标的。
    momentum_fn / lookback / threshold / schedule / cooldown_days:
        语义同 :class:`MomentumBasket`。
    """

    universe: Sequence[str]
    top_n: int = 1
    cash_buffer: float = 0.0
    momentum_fn: Union[str, MomentumFn] = "simple_return"
    lookback: int = 63
    threshold: float = -0.99
    schedule: Schedule = field(default_factory=lambda: Schedule.every_n_trading_days(1))
    cooldown_days: int = 0
    trend_filter_ma: Optional[int] = None  # 只在收盘价 > N 日均线时才持有

    def _validate(self) -> None:
        if not self.universe:
            raise ValueError("universe 不能为空")
        if self.top_n < 1 or self.top_n > len(self.universe):
            raise ValueError(f"top_n={self.top_n} 必须在 1..{len(self.universe)} 之间")
        if not 0.0 <= self.cash_buffer < 1.0:
            raise ValueError(f"cash_buffer={self.cash_buffer} 必须在 [0, 1)")

    def _build_state(self) -> _MomentumStrategyMixinState:
        self._validate()
        return _MomentumStrategyMixinState(
            momentum_fn=resolve_momentum_fn(self.momentum_fn),
            schedule=self.schedule,
            lookback=self.lookback,
            threshold=self.threshold,
            cooldown_days=self.cooldown_days,
            top_n=self.top_n,
            cash_buffer=self.cash_buffer,
            trend_ma=self.trend_filter_ma,
        )

    def _universe(self) -> List[str]:
        return list(self.universe)


# ---------------------------------------------------------------------------
# 用户视角的结果对象
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    """对外暴露的回测结果，提供方便的访问方法。"""

    raw: MultiBacktestResult

    @property
    def metrics(self) -> Dict[str, Any]:
        return self.raw.metrics

    @property
    def trades(self) -> pd.DataFrame:
        return pd.DataFrame(self.raw.trades)

    @property
    def next_signal(self) -> Dict[str, Any]:
        return self.raw.next_signal

    @property
    def universe(self) -> List[str]:
        return self.raw.universe

    def to_dict(self) -> Dict[str, Any]:
        return self.raw.to_dict()

    def summary(self) -> str:
        m = self.raw.metrics
        return (
            f"universe = {self.raw.universe}\n"
            f"区间       = {self.raw.start_date.date()} → {self.raw.end_date.date()}\n"
            f"初始资金   = {self.raw.initial_capital:.2f}\n"
            f"最终权益   = {self.raw.final_value:.2f}\n"
            f"总收益率   = {self.raw.total_return_pct:.2f}%\n"
            f"年化收益率 = {m.get('annual_return', 0):.2f}%\n"
            f"最大回撤   = {m.get('max_drawdown', 0):.2f}%\n"
            f"夏普比率   = {m.get('sharpe_ratio', 0):.2f}\n"
            f"交易次数   = {m.get('total_trades', 0)}"
        )

    def plot(self):  # pragma: no cover  (notebook only)
        """简易资产曲线图，依赖 matplotlib。"""
        import matplotlib.pyplot as plt

        df = self.trades
        if df.empty:
            print("没有交易，无法画图")
            return
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(df["date"], df["total_value"], label="组合权益")
        ax.set_xlabel("日期")
        ax.set_ylabel("总权益")
        ax.set_title("MomentumRotation 回测权益曲线")
        ax.grid(alpha=0.3)
        ax.legend()
        return fig


# ---------------------------------------------------------------------------
# run_backtest 主入口
# ---------------------------------------------------------------------------


def run_backtest(
    strategy: Union[MomentumBasket, MomentumTopN],
    start: Union[str, datetime] = "2022-01-01",
    end: Union[str, datetime, None] = None,
    initial_capital: float = 50_000,
    commission_rate: float = 0.0001,
    benchmark: Optional[str] = "000300.SS",
    risk_free_rate: float = 0.03,
    db_client: Optional[DBClient] = None,
) -> BacktestResult:
    """运行一次多标的动量回测."""
    if isinstance(strategy, MomentumBasket):
        strategy_cls = MomentumBasketStrategy
    elif isinstance(strategy, MomentumTopN):
        strategy_cls = MomentumTopNStrategy
    else:
        raise TypeError(f"不支持的策略类型: {type(strategy)}")

    start_dt = pd.to_datetime(start).to_pydatetime()
    end_dt = (
        pd.to_datetime(end).to_pydatetime()
        if end is not None
        else datetime.now()
    )

    state = strategy._build_state()
    universe = strategy._universe()

    engine = MultiBacktestEngine(db_client=db_client or DBClient())
    result = engine.run(
        universe=universe,
        start_date=start_dt,
        end_date=end_dt,
        strategy_cls=strategy_cls,
        strategy_kwargs={"state": state},
        initial_capital=initial_capital,
        commission_rate=commission_rate,
        benchmark=benchmark,
        risk_free_rate=risk_free_rate,
    )
    return BacktestResult(raw=result)


__all__ = [
    "MomentumBasket",
    "MomentumTopN",
    "Schedule",
    "BacktestResult",
    "run_backtest",
    "MOMENTUM_FUNCTIONS",
]
