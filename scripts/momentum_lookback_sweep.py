"""动量 lookback 参数扫描：从 yfinance 拉数据，绕过 MySQL，直接跑 backtrader.

用法:
    uv run python scripts/momentum_lookback_sweep.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Dict, List

import backtrader as bt
import pandas as pd
import yfinance as yf
from loguru import logger
from tabulate import tabulate

from tradingtest.analysis.metrics import PerformanceAnalyzer
from tradingtest.strategies.momentum import Schedule, resolve_momentum_fn
from tradingtest.strategies.momentum_rotation import (
    MomentumTopNStrategy,
    _MomentumStrategyMixinState,
)


# 用户给的 3 个标的 → yfinance ticker（沪市 .SH → .SS）
YF_TICKERS = {
    "159915.SZ": "159915.SZ",   # 创业板 ETF (深)
    "513100.SH": "513100.SS",   # 纳斯达克 100 ETF (沪)
    "518880.SH": "518880.SS",   # 黄金 ETF (沪)
}
START_DATE = "2021-09-01"   # 留出足够 lookback
TEST_START = "2022-01-01"
END_DATE = "2026-05-19"

INITIAL_CAPITAL = 50_000.0
COMMISSION = 0.0001
TOP_N = 1
CASH_BUFFER = 0.05


def fetch_data() -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    for orig, yf_sym in YF_TICKERS.items():
        logger.info(f"yfinance {orig} → {yf_sym}")
        df = yf.download(
            yf_sym, start=START_DATE, end=END_DATE,
            progress=False, auto_adjust=False,
        )
        if df.empty:
            raise RuntimeError(f"yfinance 没拉到 {yf_sym}")
        df = df.reset_index()
        # 多 ticker MultiIndex 处理
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
        logger.info(f"  → {len(out[orig])} bars, {df['date'].min().date()} 至 {df['date'].max().date()}")
    return out


import numpy as np


def run_one(lookback: int, data_by_symbol: Dict[str, pd.DataFrame]) -> Dict:
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
        momentum_fn=resolve_momentum_fn("simple_return"),
        schedule=Schedule.every_n_trading_days(1),
        lookback=lookback,
        threshold=-0.99,
        cooldown_days=0,
        top_n=TOP_N,
        cash_buffer=CASH_BUFFER,
    )

    cerebro.broker.setcash(INITIAL_CAPITAL)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.addstrategy(MomentumTopNStrategy, state=state)

    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    # 真实日度指标：按交易日收益率年化
    cerebro.addanalyzer(
        bt.analyzers.TimeReturn,
        _name="dailyret",
        timeframe=bt.TimeFrame.Days,
    )

    cerebro.run(fromdate=datetime.fromisoformat(TEST_START))

    strat = cerebro.runstrats[0][0]
    final_value = cerebro.broker.getvalue()

    # 日度收益率 → 真实年化收益、波动、夏普
    daily = list(strat.analyzers.dailyret.get_analysis().values())
    daily = np.asarray(daily, dtype=float)
    daily = daily[~np.isnan(daily)]
    n = len(daily)
    if n > 1:
        mean_d = daily.mean()
        std_d = daily.std(ddof=1)
        ann_return = (np.prod(1 + daily) ** (252 / n) - 1) * 100
        volatility = std_d * np.sqrt(252) * 100
        sharpe = (mean_d * 252 - 0.03) / (volatility / 100) if volatility > 0 else 0
    else:
        ann_return = volatility = sharpe = 0.0

    dd = strat.analyzers.drawdown.get_analysis()
    max_drawdown = dd.get("max", {}).get("drawdown", 0.0)

    trades_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trades_analysis.get("total", {}).get("total", 0)
    won = trades_analysis.get("won", {}).get("total", 0)
    win_rate = (won / total_trades * 100) if total_trades > 0 else 0.0

    return {
        "lookback": lookback,
        "final": final_value,
        "total_return": (final_value / INITIAL_CAPITAL - 1) * 100,
        "annual_return": ann_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "volatility": volatility,
        "total_trades": total_trades,
        "win_rate": win_rate,
    }


def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    data_by_symbol = fetch_data()
    rows: List[Dict] = []
    for lb in range(8, 31):
        try:
            row = run_one(lb, data_by_symbol)
            logger.info(
                f"lookback={lb:>2}d  annual={row['annual_return']:>7.2f}%  "
                f"max_dd={row['max_drawdown']:>6.2f}%  sharpe={row['sharpe_ratio']:>5.2f}  "
                f"vol={row['volatility']:>5.2f}%  trades={row['total_trades']}"
            )
            rows.append(row)
        except Exception as e:  # noqa: BLE001
            logger.error(f"lookback={lb} 失败: {e}")

    print()
    print("=" * 92)
    print(f"动量 Top-1 等权 (cash_buffer={CASH_BUFFER}) — lookback 扫描")
    print(f"标的: {list(YF_TICKERS)}  起始: {TEST_START}  终止: {END_DATE}")
    print("=" * 92)
    print(
        tabulate(
            [
                [
                    r["lookback"],
                    f"{r['annual_return']:+.2f}%",
                    f"{r['max_drawdown']:.2f}%",
                    f"{r['sharpe_ratio']:.2f}",
                    f"{r['volatility']:.2f}%",
                    r["total_trades"],
                    f"{r['win_rate']:.1f}%",
                    f"¥{r['final']:>10,.0f}",
                ]
                for r in rows
            ],
            headers=[
                "Lookback",
                "年化收益",
                "最大回撤",
                "夏普",
                "波动率",
                "交易",
                "胜率",
                "最终权益",
            ],
            tablefmt="github",
        )
    )

    # Top 5 by sharpe
    print()
    print("=" * 92)
    print("TOP 5 — 按夏普比率")
    print("=" * 92)
    top = sorted(rows, key=lambda r: r["sharpe_ratio"], reverse=True)[:5]
    print(
        tabulate(
            [
                [
                    r["lookback"],
                    f"{r['annual_return']:+.2f}%",
                    f"{r['max_drawdown']:.2f}%",
                    f"{r['sharpe_ratio']:.2f}",
                    f"{r['volatility']:.2f}%",
                ]
                for r in top
            ],
            headers=["Lookback", "年化收益", "最大回撤", "夏普", "波动率"],
            tablefmt="github",
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
