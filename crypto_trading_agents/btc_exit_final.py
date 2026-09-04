"""BTC final exit rules: fast on losses, structure-driven while profitable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(slots=True)
class BTCExitFinalConfig:
    loss_hard_stop_atr: float = 2.0
    loss_structure_break_buffer: float = 0.005
    time_stop_on_loss_days: int = 45
    time_stop_min_loss: float = -0.01

    profit_use_structure_exit: bool = True
    structure_lookback: int = 10
    structure_buffer_pct: float = 0.01

    profit_use_atr_trailing: bool = False
    profit_trail_atr_mult: float = 5.0

    ma_reduce_enabled: bool = True
    ma_reduce_pct: float = 0.30
    ma_fast: str = "ema20"
    ma_slow: str = "sma50"
    ma_consecutive_days: int = 3

    max_giveback_pct: float = 0.35
    giveback_min_profit_pct: float = 0.05
    time_stop_on_profit: bool = False


class BTCExitFinal:
    """Close losing positions quickly and let profitable trends follow structure."""

    def __init__(self, config: Optional[BTCExitFinalConfig] = None):
        self.config = config or BTCExitFinalConfig()
        self.reset()

    def reset(self) -> None:
        self.below_ma_count = 0
        self.ma_reduced = False

    def check_exit(
        self,
        position: dict,
        bar: dict,
        frame: Optional[pd.DataFrame] = None,
        index: int = 0,
    ) -> tuple[bool, str, float]:
        entry_price = float(position["entry_price"])
        entry_atr = float(position.get("entry_atr", bar.get("atr", entry_price * 0.02)))
        highest = float(position.get("highest_since_entry", entry_price))
        holding_days = int(position.get("holding_days", 0))
        entry_swing_low = float(position.get("entry_swing_low", entry_price * 0.95))
        close = float(bar["close"])
        current_pnl = close / entry_price - 1.0
        max_profit = highest / entry_price - 1.0

        if close <= entry_price:
            hard_stop = entry_price - self.config.loss_hard_stop_atr * entry_atr
            if close <= hard_stop:
                return True, "hard_stop", 1.0
            if close < entry_swing_low * (1 - self.config.loss_structure_break_buffer):
                return True, "structure_break_loss", 1.0
            if (
                holding_days > self.config.time_stop_on_loss_days
                and current_pnl < self.config.time_stop_min_loss
            ):
                return True, f"time_stop_loss ({holding_days}d)", 1.0
            return False, "", 0.0

        if max_profit >= self.config.giveback_min_profit_pct and highest > entry_price:
            giveback = (highest - close) / (highest - entry_price)
            if giveback >= self.config.max_giveback_pct:
                return True, f"max_giveback ({giveback:.0%})", 1.0

        if self.config.profit_use_structure_exit:
            structure_stop = self._structure_stop(position, frame, index)
            if structure_stop is not None and close < structure_stop:
                return True, f"dynamic_structure_break ({structure_stop:.2f})", 1.0

        if self.config.profit_use_atr_trailing:
            atr = float(bar.get("atr", entry_atr))
            trailing_stop = highest - self.config.profit_trail_atr_mult * atr
            if close < trailing_stop:
                return True, "atr_trailing", 1.0

        if self.config.ma_reduce_enabled and not self.ma_reduced:
            fast = bar.get(self.config.ma_fast)
            slow = bar.get(self.config.ma_slow)
            if fast is not None and slow is not None and close < fast < slow:
                self.below_ma_count += 1
            else:
                self.below_ma_count = 0
            if self.below_ma_count >= self.config.ma_consecutive_days:
                self.ma_reduced = True
                return True, f"ma_reduce ({self.below_ma_count}d)", self.config.ma_reduce_pct

        if self.config.time_stop_on_profit and holding_days > 90 and current_pnl < 0.02:
            return True, f"time_stop_profit ({holding_days}d)", 1.0

        return False, "", 0.0

    def _structure_stop(
        self,
        position: dict,
        frame: Optional[pd.DataFrame],
        index: int,
    ) -> Optional[float]:
        if frame is None or index <= 0:
            return None
        lookback = self.config.structure_lookback
        start = max(0, index - lookback)
        recent_low = float(frame["low"].iloc[start:index].min())
        stop = recent_low * (1 - self.config.structure_buffer_pct)
        # Only raise the exit above breakeven when structure itself is above entry.
        return stop if stop > float(position["entry_price"]) else None

