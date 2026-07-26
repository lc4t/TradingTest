"""离线生成一份 rotation-v1 sample JSON，方便预览前端（绕开 DB）.

输出: frontend/public/data/rotation/momentum-top1.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd
import yfinance as yf
from loguru import logger

from trading.analysis.metrics import PerformanceAnalyzer
from trading.analysis.report import trade_record_to_dict
from trading.engine.multi import MultiBacktestResult
from trading.io.rotation_export import format_rotation_for_json
from trading.strategies.momentum import Schedule, resolve_momentum_fn
from trading.strategies.momentum_rotation import (
    MomentumTopNStrategy,
    _MomentumStrategyMixinState,
)


YF_TICKERS = {
    "159915.SZ": ("159915.SZ", "创业板ETF"),
    "513100.SH": ("513100.SS", "纳指ETF"),
    "518880.SH": ("518880.SS", "黄金ETF"),
}
DATA_START = "2021-09-01"
TEST_START = "2022-01-01"
DATA_END = "2026-05-19"

OUT_PATH = Path("frontend/data/rotation/momentum-top1.json")


def fetch():
    out = {}
    for orig, (yf_sym, _name) in YF_TICKERS.items():
        df = yf.download(yf_sym, start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
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


def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    data = fetch()

    cerebro = bt.Cerebro()
    for sym, df in data.items():
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
        lookback=23,
        threshold=-0.99,
        cooldown_days=0,
        top_n=1,
        cash_buffer=0.05,
    )
    cerebro.broker.setcash(50_000)
    cerebro.broker.setcommission(commission=0.0001)
    cerebro.addstrategy(MomentumTopNStrategy, state=state)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.VWR, _name="vwr")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")
    cerebro.addanalyzer(
        bt.analyzers.TimeReturn, _name="dailyret", timeframe=bt.TimeFrame.Days
    )

    cerebro.run(fromdate=datetime.fromisoformat(TEST_START))
    strat = cerebro.runstrats[0][0]
    final_value = cerebro.broker.getvalue()

    # 1.0 PerformanceAnalyzer (含 yearly_returns 等字段)
    metrics_full = PerformanceAnalyzer.calculate_metrics(
        initial_capital=50_000,
        final_value=final_value,
        trade_records=strat.trade_records,
        analyzers_results={
            "trades": strat.analyzers.trades.get_analysis(),
            "sharpe": strat.analyzers.sharpe.get_analysis(),
            "drawdown": strat.analyzers.drawdown.get_analysis(),
            "vwr": strat.analyzers.vwr.get_analysis(),
            "sqn": strat.analyzers.sqn.get_analysis(),
            "last_date": strat.datas[0].datetime.datetime(),
        },
        benchmark_data={},
        benchmark_symbol=None,
        risk_free_rate=0.03,
    )

    # 用日度 TimeReturn 覆盖 volatility / sharpe / annual_return（修正 1.0 的稀疏交易偏差）
    daily = np.asarray(list(strat.analyzers.dailyret.get_analysis().values()), dtype=float)
    daily = daily[~np.isnan(daily)]
    if len(daily) > 1:
        ann_return = (np.prod(1 + daily) ** (252 / len(daily)) - 1) * 100
        vol = daily.std(ddof=1) * np.sqrt(252) * 100
        sharpe = (daily.mean() * 252 - 0.03) / (vol / 100) if vol > 0 else 0.0
        metrics_full["annual_return"] = ann_return
        metrics_full["cagr"] = ann_return
        metrics_full["volatility"] = vol
        metrics_full["sharpe_ratio"] = sharpe
        if metrics_full.get("max_drawdown", 0) > 0:
            metrics_full["calmar_ratio"] = ann_return / metrics_full["max_drawdown"]

    result = MultiBacktestResult(
        initial_capital=50_000,
        final_value=final_value,
        total_return_pct=(final_value / 50_000 - 1) * 100,
        metrics=metrics_full,
        trades=[trade_record_to_dict(t) for t in strat.trade_records],
        next_signal=strat._predict_next_signal(),
        universe=list(YF_TICKERS),
        start_date=datetime.fromisoformat(TEST_START),
        end_date=datetime.fromisoformat(DATA_END),
        benchmark=None,
    )

    config = {
        "universe": list(YF_TICKERS),
        "weights": None,
        "mode": "top_n",
        "topN": 1,
        "cashBuffer": 0.05,
        "momentumFn": "simple_return",
        "lookback": 23,
        "threshold": -0.99,
        "schedule": "daily",
        "cooldownDays": 0,
        "initialCapital": 50_000,
        "commissionRate": 0.0001,
        "benchmark": None,
        "riskFreeRate": 0.03,
    }

    # 用本地 name lookup (没 DB)
    payload = format_rotation_for_json(
        result,
        strategy_id="momentum-top1",
        strategy_name="动量轮动 Top-1（创业板 / 纳指 / 黄金）",
        config=config,
        db_client=None,
    )
    # 手动注入更友好的名称
    name_map = {k: v[1] for k, v in YF_TICKERS.items()}
    if payload["currentHolding"]:
        payload["currentHolding"]["name"] = name_map.get(
            payload["currentHolding"]["symbol"], payload["currentHolding"]["symbol"]
        )
    for row in payload["universeRanking"]:
        row["name"] = name_map.get(row["symbol"], row["symbol"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    logger.info(f"写入 {OUT_PATH}  ({OUT_PATH.stat().st_size} bytes)")
    logger.info(
        f"summary: 年化={payload['summary']['annualReturn']}% "
        f"回撤={payload['summary']['maxDrawdown']}% "
        f"夏普={payload['summary']['sharpe']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
