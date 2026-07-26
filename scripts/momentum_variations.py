"""动量策略的 3 个对比实验（lookback=23 固定）：

A. 5 种动量算法
B. threshold（绝对动量阈值）扫描
C. 调仓频率对比

数据：yfinance（绕开 DB）。
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Dict, List, Tuple

import backtrader as bt
import numpy as np
import pandas as pd
import yfinance as yf
from loguru import logger
from tabulate import tabulate

from trading.strategies.momentum import Schedule, resolve_momentum_fn
from trading.strategies.momentum_rotation import (
    MomentumTopNStrategy,
    _MomentumStrategyMixinState,
)


YF_TICKERS = {
    "159915.SZ": "159915.SZ",
    "513100.SH": "513100.SS",
    "518880.SH": "518880.SS",
}
DATA_START = "2021-09-01"
TEST_START = "2022-01-01"
DATA_END = "2026-05-19"
INITIAL_CAPITAL = 50_000.0
COMMISSION = 0.0001
LOOKBACK = 23
TOP_N = 1
CASH_BUFFER = 0.05


def fetch_data() -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    for orig, yf_sym in YF_TICKERS.items():
        df = yf.download(
            yf_sym, start=DATA_START, end=DATA_END,
            progress=False, auto_adjust=False,
        )
        if df.empty:
            raise RuntimeError(f"yfinance 没拉到 {yf_sym}")
        df = df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.rename(
            columns={
                "Date": "date",
                "Open": "open_price",
                "High": "high",
                "Low": "low",
                "Close": "close_price",
                "Volume": "volume",
            }
        )
        df["date"] = pd.to_datetime(df["date"])
        df = df.dropna(subset=["close_price"]).reset_index(drop=True)
        out[orig] = df[["date", "open_price", "high", "low", "close_price", "volume"]]
    return out


def run_one(
    data_by_symbol: Dict[str, pd.DataFrame],
    *,
    momentum_fn: str = "simple_return",
    lookback: int = LOOKBACK,
    threshold: float = -0.99,
    schedule: Schedule | None = None,
) -> Dict:
    cerebro = bt.Cerebro()
    for sym, df in data_by_symbol.items():
        feed = bt.feeds.PandasData(
            dataname=df,
            datetime="date",
            open="open_price",
            high="high",
            low="low",
            close="close_price",
            volume="volume",
            openinterest=-1,
        )
        feed._name = sym
        cerebro.adddata(feed, name=sym)

    state = _MomentumStrategyMixinState(
        momentum_fn=resolve_momentum_fn(momentum_fn),
        schedule=schedule or Schedule.every_n_trading_days(1),
        lookback=lookback,
        threshold=threshold,
        cooldown_days=0,
        top_n=TOP_N,
        cash_buffer=CASH_BUFFER,
    )

    cerebro.broker.setcash(INITIAL_CAPITAL)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.addstrategy(MomentumTopNStrategy, state=state)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(
        bt.analyzers.TimeReturn,
        _name="dailyret",
        timeframe=bt.TimeFrame.Days,
    )
    cerebro.run(fromdate=datetime.fromisoformat(TEST_START))
    strat = cerebro.runstrats[0][0]
    final_value = cerebro.broker.getvalue()

    daily = np.asarray(list(strat.analyzers.dailyret.get_analysis().values()), dtype=float)
    daily = daily[~np.isnan(daily)]
    n = len(daily)
    if n > 1:
        ann_return = (np.prod(1 + daily) ** (252 / n) - 1) * 100
        vol = daily.std(ddof=1) * np.sqrt(252) * 100
        sharpe = (daily.mean() * 252 - 0.03) / (vol / 100) if vol > 0 else 0.0
    else:
        ann_return = vol = sharpe = 0.0

    dd = strat.analyzers.drawdown.get_analysis()
    max_dd = dd.get("max", {}).get("drawdown", 0.0)
    ta = strat.analyzers.trades.get_analysis()
    total_trades = ta.get("total", {}).get("total", 0)
    won = ta.get("won", {}).get("total", 0)
    win_rate = (won / total_trades * 100) if total_trades > 0 else 0.0

    return {
        "annual_return": ann_return,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "volatility": vol,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "final_value": final_value,
        "calmar": ann_return / max_dd if max_dd > 0 else 0.0,
    }


def _row(label: str, r: Dict) -> List:
    return [
        label,
        f"{r['annual_return']:+.2f}%",
        f"{r['max_drawdown']:.2f}%",
        f"{r['sharpe']:.2f}",
        f"{r['volatility']:.2f}%",
        f"{r['calmar']:.2f}",
        r["total_trades"],
        f"{r['win_rate']:.1f}%",
        f"¥{r['final_value']:>10,.0f}",
    ]


HEADERS = ["", "年化收益", "最大回撤", "夏普", "波动率", "Calmar", "交易", "胜率", "最终权益"]


def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.info("拉取 yfinance 数据...")
    data = fetch_data()

    # ---- A. 5 种动量算法 ----
    print("\n" + "=" * 100)
    print(f"A. 5 种动量算法 (lookback={LOOKBACK}, threshold=-0.99, schedule=每日)")
    print("=" * 100)
    rows_a = []
    for fn in ["simple_return", "log_return", "sharpe", "weighted", "dual_12_1"]:
        # dual_12_1 默认 lookback=252，单独传入更长窗口
        lb = 252 if fn == "dual_12_1" else LOOKBACK
        r = run_one(data, momentum_fn=fn, lookback=lb)
        rows_a.append(_row(f"{fn} (lb={lb})", r))
    print(tabulate(rows_a, headers=HEADERS, tablefmt="github"))

    # ---- B. threshold 扫描 ----
    print("\n" + "=" * 100)
    print(f"B. threshold 扫描 (lookback={LOOKBACK}, simple_return, schedule=每日)")
    print("=" * 100)
    rows_b = []
    for th in [-0.99, 0.0, 0.01, 0.02, 0.05, 0.10]:
        r = run_one(data, threshold=th)
        label = f"threshold={th:+.2f}"
        rows_b.append(_row(label, r))
    print(tabulate(rows_b, headers=HEADERS, tablefmt="github"))

    # ---- C. 调仓频率对比 ----
    print("\n" + "=" * 100)
    print(f"C. 调仓频率对比 (lookback={LOOKBACK}, simple_return, threshold=-0.99)")
    print("=" * 100)
    schedules = [
        ("每个交易日", Schedule.every_n_trading_days(1)),
        ("每周一", Schedule.weekly(weekday=1)),
        ("每周第一交易日", Schedule.weekly_nth_trading_day(n=1)),
        ("每月第一交易日", Schedule.monthly_nth_trading_day(n=1)),
        ("每月 15 号", Schedule.monthly(day=15)),
    ]
    rows_c = []
    for label, sched in schedules:
        r = run_one(data, schedule=sched)
        rows_c.append(_row(label, r))
    print(tabulate(rows_c, headers=HEADERS, tablefmt="github"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
