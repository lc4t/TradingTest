"""TradingTest — 量化交易数据同步与回测工具集.

公共 API:

    from tradingtest import DBClient, SingleBacktestEngine
    from tradingtest.strategies.dual_ma import DualMAStrategy

后续 2.0 会加入 `run_backtest()` facade + 动量策略。
"""
from .data.repository import DBClient, SymbolInfo, TradingData
from .data.fetcher import (
    ADataFetcher,
    DataFetcher,
    StockDataManager,
    YFinanceFetcher,
)
from .engine.single import SingleBacktestEngine
from .strategies.dual_ma import DualMAStrategy

__all__ = [
    "DBClient",
    "SymbolInfo",
    "TradingData",
    "DataFetcher",
    "ADataFetcher",
    "StockDataManager",
    "YFinanceFetcher",
    "SingleBacktestEngine",
    "DualMAStrategy",
]
