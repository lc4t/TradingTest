"""参数寻优（grid search），并行执行多个参数组合的回测。"""
from __future__ import annotations

import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from itertools import product
from typing import Any, Dict, List, Optional

import backtrader as bt
import pandas as pd
from loguru import logger

from ..analysis.metrics import PerformanceAnalyzer
from ..data.repository import DBClient
from ..strategies.dual_ma import DualMAStrategy
from .single import (
    fetch_benchmark_daily_returns,
    fetch_symbol_data,
)


@dataclass
class BacktestData:
    """回测数据容器，跨进程传递。"""

    symbol_data: pd.DataFrame
    benchmark_data: Dict[date, float]
    symbol: str
    start_date: datetime
    end_date: datetime


def parse_range(value: str, step: float = 1.0) -> List[float]:
    """解析范围参数。

    Examples:
        "5" -> [5.0]
        "5-10" -> [5.0, 6.0, ..., 10.0]
    """
    if "-" not in value:
        return [float(value)]
    start, end = map(float, value.split("-"))
    return [round(x * step, 1) for x in range(int(start / step), int(end / step) + 1)]


_PARAM_NAME_MAP = {
    "ma_short": "short_period",
    "ma_long": "long_period",
    "chandelier_period": "chandelier_period",
    "chandelier_multiplier": "chandelier_multiplier",
    "adr_period": "adr_period",
    "adr_multiplier": "adr_multiplier",
}


def _run_single_combination_with_data(
    backtest_data: BacktestData, params: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """子进程入口：用预加载好的数据跑一次回测，返回精简结果。"""
    try:
        cerebro = bt.Cerebro()

        data_feed = bt.feeds.PandasData(
            dataname=backtest_data.symbol_data,
            datetime="date",
            open="open_price",
            high="high",
            low="low",
            close="close_price",
            volume="volume",
            openinterest=-1,
        )
        cerebro.adddata(data_feed)

        initial_capital = params.pop("initial_capital")
        commission_rate = params.pop("commission_rate")

        cerebro.broker.setcash(initial_capital)
        cerebro.broker.setcommission(commission=commission_rate)
        cerebro.addstrategy(DualMAStrategy, **params)

        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        cerebro.addanalyzer(bt.analyzers.VWR, _name="vwr")
        cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")

        results = cerebro.run()
        if not results:
            return None

        strat = results[0]

        analyzers_results = {
            "trades": strat.analyzers.trades.get_analysis(),
            "sharpe": strat.analyzers.sharpe.get_analysis(),
            "drawdown": strat.analyzers.drawdown.get_analysis(),
            "vwr": strat.analyzers.vwr.get_analysis(),
            "sqn": strat.analyzers.sqn.get_analysis(),
            "last_date": strat.data.datetime.datetime(),
        }

        metrics = PerformanceAnalyzer.calculate_metrics(
            initial_capital=initial_capital,
            final_value=cerebro.broker.getvalue(),
            trade_records=strat.trade_records,
            analyzers_results=analyzers_results,
            benchmark_data=backtest_data.benchmark_data,
            benchmark_symbol=params.get("benchmark"),
            risk_free_rate=params.get("risk_free_rate", 0.03),
        )

        params["initial_capital"] = initial_capital
        params["commission_rate"] = commission_rate

        trade_records_dict = [
            {
                "date": trade.date.strftime("%Y-%m-%d %H:%M:%S"),
                "action": trade.action,
                "price": trade.price,
                "size": trade.size,
                "value": trade.value,
                "commission": trade.commission,
                "pnl": trade.pnl,
                "total_value": trade.total_value,
                "signal_reason": trade.signal_reason,
                "cash": trade.cash,
            }
            for trade in strat.trade_records
        ]

        return {
            "params": params,
            "annual_return": metrics["annual_return"],
            "max_drawdown": metrics["max_drawdown"],
            "total_trades": metrics["total_trades"],
            "first_trade": trade_records_dict[0]["date"] if trade_records_dict else None,
            "last_trade": trade_records_dict[-1]["date"] if trade_records_dict else None,
            "full_result": {
                "metrics": metrics,
                "all_trades": trade_records_dict,
                "next_signal": strat._predict_next_signal(),
            },
        }
    except Exception as e:  # noqa: BLE001
        logger.error(f"回测失败，参数: {params}, 错误: {str(e)}")
        return None


def run_parameter_combinations(
    db_client: DBClient,
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    commission_rate: float,
    base_params: Dict[str, Any],
    market_params: Dict[str, Any],
    param_ranges: Dict[str, str],
    max_workers: Optional[int] = None,
) -> Dict[str, Any]:
    """并行运行所有参数组合，返回按多个指标排序的结果集。"""
    logger.info("正在获取回测数据...")
    symbol_data = fetch_symbol_data(db_client, symbol, start_date, end_date)
    if symbol_data.empty:
        raise ValueError("No data available for backtesting")

    benchmark_data: Dict[date, float] = {}
    if market_params.get("benchmark"):
        logger.info("正在获取基准数据...")
        benchmark_data = fetch_benchmark_daily_returns(
            db_client, market_params["benchmark"], start_date, end_date
        )

    backtest_data = BacktestData(
        symbol_data=symbol_data,
        benchmark_data=benchmark_data,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
    )

    param_combinations = []
    for param_name, param_range in param_ranges.items():
        values = parse_range(param_range)
        if param_name.endswith("_period") or param_name in ["ma_short", "ma_long"]:
            values = [int(v) for v in values]
        param_combinations.append([(param_name, v) for v in values])

    all_combinations = []
    for combo in product(*param_combinations):
        # 短期均线必须 < 长期均线
        if combo[0][1] < combo[1][1]:
            all_combinations.append(combo)

    total_combinations = len(all_combinations)
    if max_workers is None:
        max_workers = min(multiprocessing.cpu_count(), total_combinations)

    logger.info(
        f"开始并行回测，共 {total_combinations} 个参数组合，使用 {max_workers} 个进程"
    )

    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_params = {}
        for combo in all_combinations:
            params = base_params.copy()
            for name, value in dict(combo).items():
                strategy_param_name = _PARAM_NAME_MAP.get(name, name)
                params[strategy_param_name] = value
            params.update(
                {
                    "initial_capital": initial_capital,
                    "commission_rate": commission_rate,
                }
            )
            future = executor.submit(_run_single_combination_with_data, backtest_data, params)
            future_to_params[future] = params

        completed = 0
        for future in as_completed(future_to_params):
            completed += 1
            print(
                f"\r进度: {completed}/{total_combinations} "
                f"({completed / total_combinations * 100:.1f}%)",
                end="",
                flush=True,
            )
            result = future.result()
            if result is not None:
                results.append(result)

    valid_results = [r for r in results if r is not None]
    if not valid_results:
        logger.error("所有参数组合回测都失败了")
        return {"combinations": [], "best_annual_return": None}

    sorted_results = {
        "by_annual_return": sorted(
            valid_results, key=lambda x: x["annual_return"], reverse=True
        ),
        "by_sharpe": sorted(
            valid_results,
            key=lambda x: x["full_result"]["metrics"]["sharpe_ratio"],
            reverse=True,
        ),
        "by_drawdown": sorted(valid_results, key=lambda x: x["max_drawdown"]),
        "by_calmar": sorted(
            valid_results,
            key=lambda x: x["full_result"]["metrics"]["calmar_ratio"],
            reverse=True,
        ),
    }

    return {
        "combinations": sorted_results["by_annual_return"],
        "best_annual_return": sorted_results["by_annual_return"][0]
        if sorted_results["by_annual_return"]
        else None,
        "best_sharpe": sorted_results["by_sharpe"][0]
        if sorted_results["by_sharpe"]
        else None,
        "min_drawdown": sorted_results["by_drawdown"][0]
        if sorted_results["by_drawdown"]
        else None,
        "best_calmar": sorted_results["by_calmar"][0]
        if sorted_results["by_calmar"]
        else None,
    }
