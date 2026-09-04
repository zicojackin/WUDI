"""趋势底仓 + 周期加仓模块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd


class PositionLayer(str, Enum):
    BASE = "base"
    SIGNAL = "signal"


@dataclass(slots=True)
class LayerPosition:
    layer: PositionLayer
    entry_price: float
    entry_date: pd.Timestamp
    size: float
    stop_price: float
    highest_since_entry: float = 0.0

    def __post_init__(self) -> None:
        if self.highest_since_entry == 0.0:
            self.highest_since_entry = self.entry_price


@dataclass(slots=True)
class TrendBaseConfig:
    base_enabled: bool = True
    base_position_pct: float = 0.12
    base_exit_on_weekly_reversal: bool = True
    base_exit_below_sma200: bool = True
    base_trailing_atr_mult: float = 5.0
    max_signal_layers: int = 2
    signal_position_pct: float = 0.08
    min_signal_tier: str = "B"
    max_total_exposure: float = 0.50
    base_allowed_phases: set[str] = field(
        default_factory=lambda: {"markup", "recovery", "accumulation"}
    )
    base_forbidden_phases: set[str] = field(
        default_factory=lambda: {
            "distribution",
            "markdown",
            "exhaustion_extension",
            "wedge_drop",
            "ema_crossback_downside",
            "base_n_break_downside",
        }
    )


class TrendBaseManager:
    """维护底仓与信号加仓层。"""

    def __init__(self, config: Optional[TrendBaseConfig] = None):
        self.config = config or TrendBaseConfig()
        self.base_position: Optional[LayerPosition] = None
        self.signal_positions: list[LayerPosition] = []

    @property
    def has_base(self) -> bool:
        return self.base_position is not None

    @property
    def total_exposure_pct(self) -> float:
        return (
            self.config.base_position_pct if self.has_base else 0.0
        ) + len(self.signal_positions) * self.config.signal_position_pct

    def on_daily_bar(
        self,
        bar: dict,
        weekly_bar: Optional[dict],
        cycle_phase: str,
        signal_tier: Optional[str] = None,
        signal_price: Optional[float] = None,
    ) -> Optional[dict | list[dict]]:
        actions: list[dict] = []
        if self.has_base:
            base_exit = self._check_base_exit(bar, weekly_bar)
            if base_exit:
                actions.append(base_exit)
        if not self.has_base and self.config.base_enabled:
            base_entry = self._check_base_entry(bar, weekly_bar, cycle_phase)
            if base_entry:
                actions.append(base_entry)
        if signal_tier is not None and signal_price is not None:
            signal_entry = self._check_signal_entry(signal_tier, float(signal_price))
            if signal_entry:
                actions.append(signal_entry)
        for index, position in enumerate(self.signal_positions):
            signal_exit = self._check_signal_exit(position, bar)
            if signal_exit:
                actions.append({**signal_exit, "layer_index": index})

        if not actions:
            return None
        return actions[0] if len(actions) == 1 else {"multiple": actions}

    def _check_base_entry(
        self,
        bar: dict,
        weekly_bar: Optional[dict],
        cycle_phase: str,
    ) -> Optional[dict]:
        if cycle_phase in self.config.base_forbidden_phases:
            return None
        if cycle_phase not in self.config.base_allowed_phases or weekly_bar is None:
            return None
        close = float(weekly_bar.get("close", 0.0))
        ema20 = float(weekly_bar.get("ema20", 0.0))
        ema50 = float(weekly_bar.get("ema50", 0.0))
        if not (close > ema20 or ema20 > ema50):
            return None
        sma200 = float(bar.get("sma200", 0.0))
        if sma200 > 0 and float(bar["close"]) < sma200:
            return None
        return {
            "type": "open_base",
            "price": float(bar["close"]),
            "position_pct": self.config.base_position_pct,
            "reason": f"weekly up + {cycle_phase}",
        }

    def _check_base_exit(self, bar: dict, weekly_bar: Optional[dict]) -> Optional[dict]:
        if weekly_bar is not None and self.config.base_exit_on_weekly_reversal:
            close = float(weekly_bar.get("close", 0.0))
            ema20 = float(weekly_bar.get("ema20", 0.0))
            ema50 = float(weekly_bar.get("ema50", 0.0))
            if close < ema20 and ema20 < ema50:
                return {"type": "close_base", "price": float(bar["close"]), "reason": "weekly reversal"}
        sma200 = float(bar.get("sma200", 0.0))
        if self.config.base_exit_below_sma200 and sma200 > 0:
            if float(bar["close"]) < sma200 * 0.98:
                return {"type": "close_base", "price": float(bar["close"]), "reason": "below SMA200"}
        atr = float(bar.get("atr", float(bar["close"]) * 0.02))
        position = self.base_position
        if position:
            position.highest_since_entry = max(
                position.highest_since_entry,
                float(bar.get("high", bar["close"])),
            )
            trailing_stop = position.highest_since_entry - self.config.base_trailing_atr_mult * atr
            if float(bar["close"]) < trailing_stop:
                return {
                    "type": "close_base",
                    "price": float(bar["close"]),
                    "reason": "base trailing stop",
                }
        return None

    def _check_signal_entry(self, tier: str, price: float) -> Optional[dict]:
        tier_order = {"A": 3, "B": 2, "C": 1}
        minimum = tier_order.get(self.config.min_signal_tier, 2)
        if tier_order.get(tier, 0) < minimum:
            return None
        if len(self.signal_positions) >= self.config.max_signal_layers:
            return None
        if self.total_exposure_pct + self.config.signal_position_pct > self.config.max_total_exposure:
            return None
        return {
            "type": "add_signal",
            "price": price,
            "position_pct": self.config.signal_position_pct,
            "tier": tier,
            "reason": f"Tier {tier} signal add",
        }

    def _check_signal_exit(self, position: LayerPosition, bar: dict) -> Optional[dict]:
        atr = float(bar.get("atr", float(bar["close"]) * 0.02))
        close = float(bar["close"])
        if close <= position.stop_price:
            return {"type": "close_signal", "price": close, "reason": "signal stop"}
        position.highest_since_entry = max(
            position.highest_since_entry,
            float(bar.get("high", close)),
        )
        trailing_stop = position.highest_since_entry - 3.0 * atr
        if close < trailing_stop and close > position.entry_price:
            return {"type": "close_signal", "price": close, "reason": "signal trailing stop"}
        return None

    def execute_action(self, action: dict, account_equity: float, date: pd.Timestamp) -> None:
        action_type = action.get("type")
        if action_type == "open_base":
            size = account_equity * action["position_pct"] / action["price"]
            self.base_position = LayerPosition(
                PositionLayer.BASE,
                action["price"],
                date,
                size,
                action["price"] * 0.8,
            )
        elif action_type == "close_base":
            self.base_position = None
        elif action_type == "add_signal":
            size = account_equity * action["position_pct"] / action["price"]
            self.signal_positions.append(
                LayerPosition(
                    PositionLayer.SIGNAL,
                    action["price"],
                    date,
                    size,
                    action["price"] * 0.95,
                )
            )
        elif action_type == "close_signal":
            index = int(action.get("layer_index", 0))
            if 0 <= index < len(self.signal_positions):
                self.signal_positions.pop(index)

    def get_state(self) -> dict:
        return {
            "has_base": self.has_base,
            "signal_layers": len(self.signal_positions),
            "total_exposure_pct": self.total_exposure_pct,
        }
