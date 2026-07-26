"""动量函数 & Schedule 的单元测试。"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from trading.strategies.momentum import (
    MOMENTUM_FUNCTIONS,
    Schedule,
    dual_12_1,
    log_return,
    resolve_momentum_fn,
    sharpe_momentum,
    simple_return,
    weighted_momentum,
)


# ---------------------------------------------------------------------------
# 动量函数
# ---------------------------------------------------------------------------


class TestMomentumFunctions:
    def test_simple_return_known_values(self):
        closes = [100, 110]
        assert simple_return(closes, 1) == pytest.approx(0.10)

    def test_simple_return_insufficient(self):
        assert math.isnan(simple_return([10, 11], 5))

    def test_log_return_known(self):
        closes = [100, 100 * math.e]
        assert log_return(closes, 1) == pytest.approx(1.0)

    def test_log_return_nonpositive(self):
        # 出现 0 或负数应得 NaN，而不是 ValueError
        assert math.isnan(log_return([100, 0], 1))

    def test_sharpe_zero_variance_returns_nan(self):
        # 一连串相同价格 -> std=0 -> NaN
        assert math.isnan(sharpe_momentum([100] * 20, 19))

    def test_weighted_uses_full_window(self):
        # half_life 很大时退化为均值
        closes = list(range(100, 200))
        ret = weighted_momentum(closes, lookback=50, half_life=10_000)
        assert not math.isnan(ret)

    def test_dual_12_1_subtracts_recent(self):
        # 构造一个：前期猛涨，最近 1 个月平涨
        closes = list(range(100, 300))  # 200 个点
        v = dual_12_1(closes, lookback=120, short_skip=20)
        assert v > 0  # 应该是 12M 涨 - 1M 涨，仍然 > 0

    def test_registry_contains_five_keys(self):
        # 必须至少 5 种
        assert set(MOMENTUM_FUNCTIONS) >= {
            "simple_return",
            "log_return",
            "sharpe",
            "weighted",
            "dual_12_1",
        }

    def test_resolve_callable(self):
        fn = resolve_momentum_fn("simple_return")
        assert fn is simple_return

    def test_resolve_invalid(self):
        with pytest.raises(ValueError):
            resolve_momentum_fn("not_real")


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


def _walk(sched: Schedule, start: date, days: int) -> list[date]:
    """按工作日推进 `days` 天，返回 fired 的日期。"""
    sched.reset()
    fired: list[date] = []
    cur = start
    seen = 0
    while seen < days:
        if cur.weekday() < 5:
            if sched.should_fire(cur):
                fired.append(cur)
            seen += 1
        cur += timedelta(days=1)
    return fired


class TestSchedule:
    def test_every_1_trading_day_fires_every_day(self):
        fired = _walk(Schedule.every_n_trading_days(1), date(2022, 1, 3), 10)
        assert len(fired) == 10

    def test_every_5_trading_days(self):
        fired = _walk(Schedule.every_n_trading_days(5), date(2022, 1, 3), 15)
        # 第 1, 6, 11 天 fire
        assert len(fired) == 3

    def test_weekly_monday(self):
        # 跨 3 个完整周
        fired = _walk(Schedule.weekly(weekday=1), date(2022, 1, 3), 15)
        assert len(fired) == 3
        for d in fired:
            assert d.isoweekday() == 1

    def test_weekly_nth_trading_day(self):
        # 每周第 3 个交易日，2022-01-03 起 3 周
        fired = _walk(Schedule.weekly_nth_trading_day(n=3), date(2022, 1, 3), 15)
        assert len(fired) == 3

    def test_monthly_calendar_day(self):
        # 65 个工作日 ≈ 跨 4 个月（Jan / Feb / Mar / Apr）
        fired = _walk(Schedule.monthly(day=1), date(2022, 1, 3), 65)
        assert len(fired) == 4
        # 月份必须互不相同
        months = {d.month for d in fired}
        assert len(months) == 4

    def test_monthly_nth_trading_day(self):
        fired = _walk(Schedule.monthly_nth_trading_day(n=1), date(2022, 1, 3), 65)
        assert len(fired) == 4
        # 每月触发的应该是该月第一个工作日
        for d in fired:
            assert d.weekday() < 5

    def test_invalid_n_rejected(self):
        with pytest.raises(ValueError):
            Schedule.every_n_trading_days(0)
        with pytest.raises(ValueError):
            Schedule.weekly(weekday=7)
        with pytest.raises(ValueError):
            Schedule.monthly(day=32)
