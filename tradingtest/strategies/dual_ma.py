"""双均线策略（DualMAStrategy）+ 吊灯/ADR 止损。

行为与 1.0 版本一致，仅做模块迁移。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import backtrader as bt
import pandas as pd
from loguru import logger

from .base import TradeRecord
from .signals import SignalCalculator


class DualMAStrategy(bt.Strategy):
    """双均线策略"""

    params = (
        ("short_period", 5),
        ("long_period", 20),
        ("chandelier_period", 22),
        ("chandelier_multiplier", 3.0),
        ("adr_period", 20),
        ("adr_multiplier", 1.0),
        ("use_ma", True),
        ("use_chandelier", False),
        ("use_adr", False),
        ("trade_start_time", None),
        ("trade_end_time", None),
        ("position_size", 0.95),
    )

    def __init__(self):
        self.short_ma = bt.indicators.SMA(self.data.close, period=self.params.short_period)
        self.long_ma = bt.indicators.SMA(self.data.close, period=self.params.long_period)

        if self.params.use_chandelier:
            self.atr = bt.indicators.ATR(self.data, period=self.params.chandelier_period)
            self.highest = bt.indicators.Highest(
                self.data.high, period=self.params.chandelier_period
            )

        if self.params.use_adr:
            self.daily_range = self.data.high - self.data.low
            self.adr = bt.indicators.SMA(self.daily_range, period=self.params.adr_period)

        self.order = None
        self.entry_price = None
        self.buy_price = None
        self.buy_comm = None
        self.signal_calculator = SignalCalculator()
        self.trade_records: List[TradeRecord] = []

        self.trade_start = None
        self.trade_end = None
        if self.params.trade_start_time:
            self.trade_start = pd.Timestamp(self.params.trade_start_time).time()
        if self.params.trade_end_time:
            self.trade_end = pd.Timestamp(self.params.trade_end_time).time()

    def _is_trading_allowed(self) -> bool:
        if not (self.trade_start and self.trade_end):
            return True
        current_time = self.data.datetime.time()
        return self.trade_start <= current_time <= self.trade_end

    def notify_trade(self, trade):
        pass

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                self.buy_comm = order.executed.comm
                self.entry_price = order.executed.price

                size = abs(order.executed.size)
                position_value = order.executed.price * size
                cash_after_buy = self.broker.get_cash()
                total_value = cash_after_buy + position_value

                self.trade_records.append(
                    TradeRecord(
                        date=self.data.datetime.datetime(),
                        action="BUY",
                        price=order.executed.price,
                        size=size,
                        value=position_value,
                        commission=order.executed.comm,
                        pnl=0.0,
                        total_value=total_value,
                        signal_reason=self._get_detailed_signal_reason("MA Cross Buy"),
                        cash=cash_after_buy,
                    )
                )

                logger.debug(
                    f"Buy Executed - Price: {order.executed.price:.3f}, "
                    f"Size: {size}, "
                    f"Value: {position_value:.2f}, "
                    f"Commission: {order.executed.comm:.2f}, "
                    f"Cash: {cash_after_buy:.2f}, "
                    f"Total Value: {total_value:.2f}"
                )

            else:
                sell_price = order.executed.price
                sell_size = abs(order.executed.size)
                sell_value = sell_price * sell_size
                sell_commission = order.executed.comm

                buy_price = self.buy_price
                buy_size = sell_size
                buy_value = buy_price * buy_size
                buy_commission = self.buy_comm

                total_commission = buy_commission + sell_commission
                pnl = (sell_value - buy_value) - total_commission

                logger.debug(
                    f"\n盈亏计算过程:"
                    f"\n1. 买入: price={buy_price:.4f} size={buy_size} "
                    f"value={buy_value:.4f} fee={buy_commission:.4f}"
                    f"\n2. 卖出: price={sell_price:.4f} size={sell_size} "
                    f"value={sell_value:.4f} fee={sell_commission:.4f}"
                    f"\n3. 差价={sell_value - buy_value:.4f} "
                    f"总手续费={total_commission:.4f} 净盈亏={pnl:.4f}"
                )

                cash_after_sell = self.broker.get_cash()
                total_value = cash_after_sell

                self.trade_records.append(
                    TradeRecord(
                        date=self.data.datetime.datetime(),
                        action="SELL",
                        price=sell_price,
                        size=sell_size,
                        value=sell_value,
                        commission=sell_commission,
                        pnl=pnl,
                        total_value=total_value,
                        signal_reason=self._get_detailed_signal_reason(self._last_signal_reason),
                        cash=cash_after_sell,
                    )
                )

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            logger.warning(
                f"Order Failed - Status: {order.status} - "
                f"Reason: {order.getstatusname()} "
                f"Time: {self.data.datetime.datetime()}"
            )

        self.order = None

    def _calculate_entry_signal(self) -> bool:
        if not self.params.use_ma:
            return False
        return self.signal_calculator.check_ma_signal(
            self.short_ma[0], self.long_ma[0], self.short_ma[-1], self.long_ma[-1]
        )

    def _calculate_exit_signals(self) -> Tuple[bool, str]:
        if self.params.use_ma:
            if self.signal_calculator.check_ma_exit(
                self.short_ma[0], self.long_ma[0], self.short_ma[-1], self.long_ma[-1]
            ):
                return True, "MA Cross"

        if self.params.use_chandelier:
            if self.signal_calculator.check_chandelier_exit(
                self.data.close[0],
                self.highest[0],
                self.atr[0],
                self.params.chandelier_multiplier,
            ):
                return True, "Chandelier Exit"

        if self.params.use_adr and self.entry_price is not None:
            if self.signal_calculator.check_adr_exit(
                self.data.close[0],
                self.entry_price,
                self.adr[0],
                self.params.adr_multiplier,
            ):
                return True, "ADR Stop"

        return False, ""

    def next(self):
        if self.order:
            return

        if not self._is_trading_allowed():
            return

        if not self.position:
            if self._calculate_entry_signal():
                cash = self.broker.get_cash() * self.params.position_size
                size = int(cash / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
                    self._last_signal_reason = "MA Cross Buy"
                    logger.debug(
                        f"Buy Order Created - Price: {self.data.close[0]:.2f}, Size: {size}"
                    )
        else:
            should_exit, exit_reason = self._calculate_exit_signals()
            if should_exit:
                self.order = self.sell(size=self.position.size)
                self._last_signal_reason = exit_reason
                logger.debug(
                    f"Sell Order Created - Price: {self.data.close[0]:.2f}, "
                    f"Size: {self.position.size}, Reason: {exit_reason}"
                )

    def _get_detailed_signal_reason(self, signal_type: str) -> str:
        if signal_type == "MA Cross Buy":
            return (
                f"MA交叉买入 [MA{self.params.short_period}={self.short_ma[0]:.3f} > "
                f"MA{self.params.long_period}={self.long_ma[0]:.3f}]"
            )
        elif signal_type == "MA Cross":
            return (
                f"MA交叉卖出 [MA{self.params.short_period}={self.short_ma[0]:.3f} < "
                f"MA{self.params.long_period}={self.long_ma[0]:.3f}]"
            )
        elif signal_type == "Chandelier Exit":
            stop_price = self.highest[0] - (self.params.chandelier_multiplier * self.atr[0])
            return (
                f"吊灯止损 [ATR={self.atr[0]:.3f}, 最高价={self.highest[0]:.3f}, "
                f"止损价={stop_price:.3f}]"
            )
        elif signal_type == "ADR Stop":
            stop_price = self.entry_price - (self.params.adr_multiplier * self.adr[0])
            return (
                f"ADR止损 [ADR={self.adr[0]:.3f}, 入场价={self.entry_price:.3f}, "
                f"止损价={stop_price:.3f}]"
            )
        return signal_type

    def _predict_next_signal(self) -> Dict:
        """预测下一个交易信号。"""
        current_position = bool(self.position)

        latest_date = self.data.datetime.datetime()
        latest_prices = {
            "open": self.data.open[-1],
            "close": self.data.close[-1],
            "high": self.data.high[-1],
            "low": self.data.low[-1],
        }

        signal = {
            "action": "观察",
            "conditions": [],
            "stop_loss": None,
            "position_info": None,
            "prices": latest_prices,
            "timestamp": latest_date.strftime("%Y-%m-%d"),
        }

        short_ma = self.short_ma[0]
        long_ma = self.long_ma[0]
        prev_short_ma = self.short_ma[-1]
        prev_long_ma = self.long_ma[-1]

        if current_position:
            last_buy = next(
                (t for t in reversed(self.trade_records) if t.action == "BUY"), None
            )
            if last_buy:
                current_price = self.data.close[0]
                unrealized_pnl = (current_price - last_buy.price) * last_buy.size
                unrealized_pnl_pct = ((current_price / last_buy.price) - 1) * 100

                signal["action"] = "持有"
                signal["position_info"] = {
                    "entry_date": last_buy.date.strftime("%Y-%m-%d %H:%M:%S"),
                    "entry_price": last_buy.price,
                    "position_size": last_buy.size,
                    "position_value": last_buy.value,
                    "current_price": current_price,
                    "current_value": current_price * last_buy.size,
                    "cost": last_buy.value,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                }

            if self.params.use_chandelier:
                stop_price = self.highest[0] - (
                    self.params.chandelier_multiplier * self.atr[0]
                )
                signal["stop_loss"] = {
                    "type": "吊灯止损",
                    "price": stop_price,
                    "distance_pct": (
                        (self.data.close[0] - stop_price) / self.data.close[0]
                    )
                    * 100,
                }

            if self.params.use_adr:
                stop_price = self.entry_price - (self.params.adr_multiplier * self.adr[0])
                signal["stop_loss"] = {
                    "type": "ADR止损",
                    "price": stop_price,
                    "distance_pct": (
                        (self.data.close[0] - stop_price) / self.data.close[0]
                    )
                    * 100,
                }

            should_exit, exit_reason = self._calculate_exit_signals()
            if should_exit:
                signal["action"] = "卖出"
                signal["conditions"].append(exit_reason)

        else:
            if self.signal_calculator.check_ma_signal(
                short_ma, long_ma, prev_short_ma, prev_long_ma
            ):
                signal["action"] = "买入"
                signal["conditions"].append(
                    f"MA{self.params.short_period}({short_ma:.2f}) > "
                    f"MA{self.params.long_period}({long_ma:.2f})"
                )

        return signal
