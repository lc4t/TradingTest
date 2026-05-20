"""多标的回测引擎，给动量轮动一类的策略用。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Type

import backtrader as bt
import pandas as pd
from loguru import logger

from ..analysis.metrics import PerformanceAnalyzer
from ..analysis.report import trade_record_to_dict
from ..data.repository import DBClient
from .single import (
    _attach_analyzers,
    _make_data_feed,
    fetch_benchmark_daily_returns,
    fetch_symbol_data,
)


@dataclass
class MultiBacktestResult:
    """结构化结果，方便 facade 直接吐给用户."""

    initial_capital: float
    final_value: float
    total_return_pct: float
    metrics: Dict[str, Any]
    trades: List[Dict[str, Any]]
    next_signal: Dict[str, Any]
    universe: List[str]
    start_date: datetime
    end_date: datetime
    benchmark: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "final_value": self.final_value,
            "total_return": self.total_return_pct,
            "metrics": self.metrics,
            "all_trades": self.trades,
            "trades": self.trades[-20:],
            "next_signal": self.next_signal,
            "universe": self.universe,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "benchmark": self.benchmark,
        }


@dataclass
class MultiBacktestEngine:
    """多标的回测引擎。

    与 SingleBacktestEngine 的差别：同时挂多个 PandasData feed，
    策略类负责跨 feed 决策（典型：动量轮动）。
    """

    db_client: DBClient

    def run(
        self,
        universe: List[str],
        start_date: datetime,
        end_date: datetime,
        strategy_cls: Type[bt.Strategy],
        strategy_kwargs: Dict[str, Any],
        initial_capital: float,
        commission_rate: float = 0.0001,
        benchmark: Optional[str] = "000300.SS",
        risk_free_rate: float = 0.03,
    ) -> MultiBacktestResult:
        if not universe:
            raise ValueError("universe 不能为空")

        # 1) 加载数据并校验
        data_by_symbol: Dict[str, pd.DataFrame] = {}
        for symbol in universe:
            df = fetch_symbol_data(self.db_client, symbol, start_date, end_date)
            if df.empty:
                raise ValueError(f"{symbol} 在 [{start_date.date()}, {end_date.date()}] 区间无数据")
            data_by_symbol[symbol] = df

        # 2) 组装 cerebro
        cerebro = bt.Cerebro()
        for symbol, df in data_by_symbol.items():
            feed = _make_data_feed(df)
            feed._name = symbol
            cerebro.adddata(feed, name=symbol)

        cerebro.broker.setcash(initial_capital)
        cerebro.broker.setcommission(commission=commission_rate)
        cerebro.addstrategy(strategy_cls, **strategy_kwargs)
        _attach_analyzers(cerebro)

        # 3) 跑
        logger.info(
            f"多标的回测启动: universe={universe} "
            f"strategy={strategy_cls.__name__} "
            f"start={start_date.date()} end={end_date.date()}"
        )
        results = cerebro.run()
        if not results:
            raise RuntimeError("backtrader 未返回任何结果")
        strat = results[0]

        # 4) metrics
        benchmark_returns: Dict[date, float] = {}
        if benchmark:
            benchmark_returns = fetch_benchmark_daily_returns(
                self.db_client, benchmark, start_date, end_date
            )

        analyzers_results = {
            "trades": strat.analyzers.trades.get_analysis(),
            "sharpe": strat.analyzers.sharpe.get_analysis(),
            "drawdown": strat.analyzers.drawdown.get_analysis(),
            "vwr": strat.analyzers.vwr.get_analysis(),
            "sqn": strat.analyzers.sqn.get_analysis(),
            "last_date": strat.datas[0].datetime.datetime(),
        }
        metrics = PerformanceAnalyzer.calculate_metrics(
            initial_capital=initial_capital,
            final_value=cerebro.broker.getvalue(),
            trade_records=strat.trade_records,
            analyzers_results=analyzers_results,
            benchmark_data=benchmark_returns,
            benchmark_symbol=benchmark,
            risk_free_rate=risk_free_rate,
            daily_returns_series=strat.analyzers.dailyret.get_analysis(),
        )

        final_value = cerebro.broker.getvalue()
        total_return = ((final_value / initial_capital) - 1) * 100

        return MultiBacktestResult(
            initial_capital=initial_capital,
            final_value=final_value,
            total_return_pct=total_return,
            metrics=metrics,
            trades=[trade_record_to_dict(t) for t in strat.trade_records],
            next_signal=strat._predict_next_signal(),
            universe=list(universe),
            start_date=start_date,
            end_date=end_date,
            benchmark=benchmark,
        )
