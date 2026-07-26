"""策略层共享类型与协议。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TradeRecord:
    """详细交易记录（单标的）。"""

    date: datetime
    action: str  # "BUY" or "SELL"
    price: float
    size: int
    value: float
    commission: float
    pnl: float
    total_value: float
    signal_reason: str
    cash: float
