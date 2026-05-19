"""动量计算函数库 + 调仓日历 (Schedule)。

提供 5 种常见动量计算方式，全部接受一段 close 价格序列，返回一个标量。
长度不足时返回 NaN。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, Optional, Sequence

import numpy as np


MomentumFn = Callable[[Sequence[float], int], float]
"""动量函数签名：(closes, lookback) -> 标量

closes: 时间升序的收盘价序列（最后一个是当前 bar）。
lookback: 用到的回望窗口（交易日数）。
"""


# ---------------------------------------------------------------------------
# 5 种动量算法
# ---------------------------------------------------------------------------


def simple_return(closes: Sequence[float], lookback: int) -> float:
    """简单收益率: closes[-1] / closes[-1-lookback] - 1.

    最经典、最普遍的动量定义。
    """
    if len(closes) <= lookback:
        return float("nan")
    return closes[-1] / closes[-1 - lookback] - 1.0


def log_return(closes: Sequence[float], lookback: int) -> float:
    """对数收益率: ln(closes[-1] / closes[-1-lookback]).

    对极端涨跌不敏感，适合做横截面比较。
    """
    if len(closes) <= lookback:
        return float("nan")
    ratio = closes[-1] / closes[-1 - lookback]
    if ratio <= 0:
        return float("nan")
    return math.log(ratio)


def sharpe_momentum(closes: Sequence[float], lookback: int) -> float:
    """风险调整动量: 年化日均对数收益 / 年化日波动 (Sharpe-like).

    偏好"稳定上涨"而非"暴涨"的标的。
    """
    if len(closes) <= lookback:
        return float("nan")
    window = np.asarray(closes[-1 - lookback : ], dtype=float)
    if (window <= 0).any():
        return float("nan")
    daily_log_returns = np.diff(np.log(window))
    if daily_log_returns.size < 2:
        return float("nan")
    mean = daily_log_returns.mean()
    std = daily_log_returns.std(ddof=1)
    if std == 0:
        return float("nan")
    annual_factor = math.sqrt(252)
    return (mean / std) * annual_factor


def weighted_momentum(
    closes: Sequence[float],
    lookback: int,
    half_life: int = 21,
) -> float:
    """指数衰减加权动量: 越近的日对数收益权重越大.

    half_life 控制衰减速度（默认 21 个交易日 ~= 1 个月）。
    """
    if len(closes) <= lookback:
        return float("nan")
    window = np.asarray(closes[-1 - lookback : ], dtype=float)
    if (window <= 0).any():
        return float("nan")
    daily_log_returns = np.diff(np.log(window))
    if daily_log_returns.size == 0:
        return float("nan")
    decay = math.log(2) / max(half_life, 1)
    n = daily_log_returns.size
    # 最近的 idx = n-1, 最远的 idx = 0
    weights = np.exp(-decay * (n - 1 - np.arange(n)))
    weights /= weights.sum()
    return float(np.dot(weights, daily_log_returns)) * n  # 把日均还原为窗口总和


def dual_12_1(
    closes: Sequence[float],
    lookback: int = 252,
    short_skip: int = 21,
) -> float:
    """12-1 月动量: lookback 期累计对数收益 − 最近 short_skip 天的对数收益.

    经典论文 (Asness 等) 的设计，可以减小短期反转噪声。默认参数：
        - lookback=252 (12 个月)
        - short_skip=21 (1 个月)
    """
    if len(closes) <= lookback:
        return float("nan")
    # 总对数收益
    total = math.log(closes[-1] / closes[-1 - lookback])
    if short_skip <= 0:
        return total
    if len(closes) <= short_skip:
        return total
    # 最近 short_skip 天对数收益
    recent = math.log(closes[-1] / closes[-1 - short_skip])
    return total - recent


MOMENTUM_FUNCTIONS: Dict[str, MomentumFn] = {
    "simple_return": simple_return,
    "log_return": log_return,
    "sharpe": sharpe_momentum,
    "weighted": weighted_momentum,
    "dual_12_1": dual_12_1,
}
"""可用动量函数注册表，供按 key 查找。"""


def resolve_momentum_fn(name_or_callable) -> MomentumFn:
    """允许传字符串 key 或自定义可调用对象。"""
    if callable(name_or_callable):
        return name_or_callable
    if name_or_callable not in MOMENTUM_FUNCTIONS:
        valid = ", ".join(sorted(MOMENTUM_FUNCTIONS))
        raise ValueError(
            f"未知动量函数 {name_or_callable!r}，可选: {valid} 或传入自定义 callable"
        )
    return MOMENTUM_FUNCTIONS[name_or_callable]


# ---------------------------------------------------------------------------
# 调仓日历 (Schedule)
# ---------------------------------------------------------------------------


@dataclass
class Schedule:
    """决定每个交易日是否产生 rebalance 信号.

    通过工厂方法构造：
        Schedule.every_n_trading_days(1)          # 每个交易日 (默认)
        Schedule.weekly(weekday=1)                # 每周一 (ISO: 周一=1)
        Schedule.weekly_nth_trading_day(n=1)      # 每周第 N 个交易日
        Schedule.monthly(day=1)                   # 每月 day 号 (自然日)
        Schedule.monthly_nth_trading_day(n=1)     # 每月第 N 个交易日
    """

    kind: str
    n: int = 1
    weekday: int = 1
    day: int = 1
    # 内部状态
    _last_fire_date: Optional[date] = None
    _trading_days_since_fire: int = 0
    _this_week: Optional[int] = None  # ISO week
    _this_month: Optional[int] = None
    _trading_days_in_week: int = 0
    _trading_days_in_month: int = 0
    _fired_this_week: bool = False
    _fired_this_month: bool = False

    @staticmethod
    def every_n_trading_days(n: int) -> "Schedule":
        if n < 1:
            raise ValueError("n 必须 >= 1")
        return Schedule(kind="every_n", n=n)

    @staticmethod
    def weekly(weekday: int = 1) -> "Schedule":
        if not 1 <= weekday <= 5:
            raise ValueError("weekday 必须在 1..5 之间（仅工作日有效）")
        return Schedule(kind="weekly", weekday=weekday)

    @staticmethod
    def weekly_nth_trading_day(n: int = 1) -> "Schedule":
        if not 1 <= n <= 5:
            raise ValueError("n 必须在 1..5 之间")
        return Schedule(kind="weekly_nth", n=n)

    @staticmethod
    def monthly(day: int = 1) -> "Schedule":
        if not 1 <= day <= 31:
            raise ValueError("day 必须在 1..31 之间")
        return Schedule(kind="monthly", day=day)

    @staticmethod
    def monthly_nth_trading_day(n: int = 1) -> "Schedule":
        if not 1 <= n <= 31:
            raise ValueError("n 必须在 1..31 之间")
        return Schedule(kind="monthly_nth", n=n)

    # -----------------------------------------------------------------
    def reset(self) -> None:
        """回测开始前调用，清掉状态。"""
        self._last_fire_date = None
        self._trading_days_since_fire = 0
        self._this_week = None
        self._this_month = None
        self._trading_days_in_week = 0
        self._trading_days_in_month = 0
        self._fired_this_week = False
        self._fired_this_month = False

    def should_fire(self, today: date) -> bool:
        """传入"当前交易日"，返回是否应该 rebalance.

        必须每个交易日按顺序调用一次（即便答案是 False），内部状态依赖此前提.
        """
        iso_year, iso_week, _ = today.isocalendar()
        week_id = (iso_year, iso_week)
        month_id = (today.year, today.month)

        # 新的一周
        if self._this_week != week_id:
            self._this_week = week_id
            self._trading_days_in_week = 0
            self._fired_this_week = False
        self._trading_days_in_week += 1

        # 新的一月
        if self._this_month != month_id:
            self._this_month = month_id
            self._trading_days_in_month = 0
            self._fired_this_month = False
        self._trading_days_in_month += 1

        self._trading_days_since_fire += 1

        fired = False
        if self.kind == "every_n":
            # 第一次或满足间隔即触发
            if self._last_fire_date is None or self._trading_days_since_fire >= self.n:
                fired = True

        elif self.kind == "weekly":
            # ISO weekday: Monday=1 ... Friday=5
            if (
                not self._fired_this_week
                and today.isoweekday() == self.weekday
            ):
                fired = True

        elif self.kind == "weekly_nth":
            if (
                not self._fired_this_week
                and self._trading_days_in_week == self.n
            ):
                fired = True

        elif self.kind == "monthly":
            # 第一次 day >= self.day 的交易日
            if not self._fired_this_month and today.day >= self.day:
                fired = True

        elif self.kind == "monthly_nth":
            if (
                not self._fired_this_month
                and self._trading_days_in_month == self.n
            ):
                fired = True

        if fired:
            self._last_fire_date = today
            self._trading_days_since_fire = 0
            self._fired_this_week = True
            self._fired_this_month = True

        return fired

    def __repr__(self) -> str:  # 让日志更友好
        if self.kind == "every_n":
            return f"Schedule.every_n_trading_days({self.n})"
        if self.kind == "weekly":
            return f"Schedule.weekly(weekday={self.weekday})"
        if self.kind == "weekly_nth":
            return f"Schedule.weekly_nth_trading_day(n={self.n})"
        if self.kind == "monthly":
            return f"Schedule.monthly(day={self.day})"
        if self.kind == "monthly_nth":
            return f"Schedule.monthly_nth_trading_day(n={self.n})"
        return f"Schedule({self.kind!r})"
