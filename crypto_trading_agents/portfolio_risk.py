"""组合回撤控制、分批建仓与滑点模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd


class RiskLevel(str, Enum):
    NORMAL = "normal"
    CAUTIOUS = "cautious"
    DEFENSIVE = "defensive"
    HALT = "halt"


@dataclass(slots=True)
class PortfolioRiskConfig:
    cautious_dd_threshold: float = -0.05
    defensive_dd_threshold: float = -0.10
    halt_dd_threshold: float = -0.15
    risk_multipliers: dict[str, float] = field(default_factory=lambda: {
        RiskLevel.NORMAL.value: 1.0,
        RiskLevel.CAUTIOUS.value: 0.7,
        RiskLevel.DEFENSIVE.value: 0.4,
        RiskLevel.HALT.value: 0.0,
    })
    recovery_days: int = 10
    max_consecutive_losses: int = 4
    consecutive_loss_multiplier: float = 0.5
    max_daily_loss: float = -0.03
    max_weekly_loss: float = -0.06


class PortfolioRiskManager:
    """根据回撤、连续亏损和日/周亏损动态调整风险预算。"""

    def __init__(self, config: Optional[PortfolioRiskConfig] = None):
        self.config = config or PortfolioRiskConfig()
        self.peak_equity = 0.0
        self.current_equity = 0.0
        self.consecutive_losses = 0
        self.risk_level = RiskLevel.NORMAL
        self.halt_start_date: Optional[pd.Timestamp] = None
        self.daily_pnl_history: list[float] = []

    def update(
        self,
        current_equity: float,
        date: pd.Timestamp,
        trade_pnl: Optional[float] = None,
    ) -> tuple[RiskLevel, float]:
        self.peak_equity = max(self.peak_equity, current_equity)
        self.current_equity = current_equity
        drawdown = (
            (current_equity - self.peak_equity) / self.peak_equity
            if self.peak_equity > 0
            else 0.0
        )
        if trade_pnl is not None:
            self.daily_pnl_history.append(float(trade_pnl))
            self.consecutive_losses = self.consecutive_losses + 1 if trade_pnl < 0 else 0

        self.risk_level = self._determine_risk_level(drawdown)
        if self.risk_level == RiskLevel.HALT:
            if self.halt_start_date is None:
                self.halt_start_date = date
            elif (
                (date - self.halt_start_date).days >= self.config.recovery_days
                and drawdown > self.config.cautious_dd_threshold
            ):
                self.risk_level = RiskLevel.CAUTIOUS
        else:
            self.halt_start_date = None

        multiplier = self.config.risk_multipliers[self.risk_level.value]
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            multiplier *= self.config.consecutive_loss_multiplier
        if self.daily_pnl_history:
            if self.daily_pnl_history[-1] < self.config.max_daily_loss:
                multiplier = 0.0
            if len(self.daily_pnl_history) >= 7:
                weekly_pnl = sum(self.daily_pnl_history[-7:])
                if weekly_pnl < self.config.max_weekly_loss:
                    multiplier = 0.0
        return self.risk_level, multiplier

    def _determine_risk_level(self, drawdown: float) -> RiskLevel:
        if drawdown <= self.config.halt_dd_threshold:
            return RiskLevel.HALT
        if drawdown <= self.config.defensive_dd_threshold:
            return RiskLevel.DEFENSIVE
        if drawdown <= self.config.cautious_dd_threshold:
            return RiskLevel.CAUTIOUS
        return RiskLevel.NORMAL

    def get_status(self) -> dict:
        drawdown = (
            (self.current_equity - self.peak_equity) / self.peak_equity
            if self.peak_equity > 0
            else 0.0
        )
        return {
            "risk_level": self.risk_level.value,
            "current_drawdown": drawdown,
            "consecutive_losses": self.consecutive_losses,
            "peak_equity": self.peak_equity,
            "current_equity": self.current_equity,
        }


@dataclass(slots=True)
class SplitEntryConfig:
    n_splits: int = 3
    split_ratios: list[float] = field(default_factory=lambda: [0.5, 0.3, 0.2])
    price_spacing_atr: float = 0.5
    max_wait_bars: int = 5
    cancel_unfilled: bool = True


class SplitEntryExecutor:
    """第一批市价建仓，剩余批次用低于参考价的限价单模拟。"""

    def __init__(self, config: Optional[SplitEntryConfig] = None):
        self.config = config or SplitEntryConfig()
        self.reset()

    def reset(self) -> None:
        self.pending_orders: list[dict] = []
        self.filled_orders: list[dict] = []
        self.bars_waited = 0

    def create_orders(self, entry_price: float, atr: float, total_size: float) -> list[dict]:
        self.reset()
        orders: list[dict] = []
        for index, ratio in enumerate(self.config.split_ratios[: self.config.n_splits]):
            size = total_size * ratio
            if index == 0:
                order = {
                    "batch": 1,
                    "type": "market",
                    "price": entry_price,
                    "size": size,
                    "status": "filled",
                    "fill_price": entry_price,
                }
                self.filled_orders.append(order)
            else:
                order = {
                    "batch": index + 1,
                    "type": "limit",
                    "price": entry_price - index * self.config.price_spacing_atr * atr,
                    "size": size,
                    "status": "pending",
                }
                self.pending_orders.append(order)
            orders.append(order)
        return orders

    def check_fills(self, bar: dict) -> list[dict]:
        self.bars_waited += 1
        newly_filled = []
        low = float(bar.get("low", bar.get("close", 0.0)))
        for order in self.pending_orders[:]:
            if low <= order["price"]:
                order["status"] = "filled"
                order["fill_price"] = order["price"]
                self.filled_orders.append(order)
                self.pending_orders.remove(order)
                newly_filled.append(order)
        if self.bars_waited >= self.config.max_wait_bars and self.config.cancel_unfilled:
            for order in self.pending_orders[:]:
                order["status"] = "cancelled"
                self.pending_orders.remove(order)
        return newly_filled

    def get_average_fill_price(self) -> float:
        total_cost = sum(
            order["fill_price"] * order["size"]
            for order in self.filled_orders
            if "fill_price" in order
        )
        total_size = sum(order["size"] for order in self.filled_orders)
        return total_cost / total_size if total_size else 0.0

    def get_fill_ratio(self) -> float:
        planned = sum(order["size"] for order in self.filled_orders + self.pending_orders)
        filled = sum(order["size"] for order in self.filled_orders)
        return filled / planned if planned else 0.0


class SlippageModel:
    """基于参与率和波动率估算滑点。"""

    def __init__(
        self,
        base_slippage: float = 0.0005,
        volume_impact_factor: float = 0.1,
    ):
        self.base_slippage = base_slippage
        self.volume_impact_factor = volume_impact_factor

    def estimate_slippage(
        self,
        order_size_usd: float,
        bar_volume_usd: float,
        volatility: float = 0.02,
    ) -> float:
        if bar_volume_usd <= 0:
            return min(self.base_slippage * 3.0, 0.01)
        participation = order_size_usd / bar_volume_usd
        slippage = (
            self.base_slippage
            + self.volume_impact_factor * participation
            + volatility * 0.1
        )
        return min(slippage, 0.01)

    def adjust_fill_price(
        self,
        expected_price: float,
        order_size_usd: float,
        bar_volume_usd: float,
        direction: str = "buy",
        volatility: float = 0.02,
    ) -> float:
        slippage = self.estimate_slippage(order_size_usd, bar_volume_usd, volatility)
        return expected_price * (1 + slippage if direction == "buy" else 1 - slippage)
