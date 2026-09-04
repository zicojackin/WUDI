"""ETH Exit V2：更宽跟踪、日线部分减仓、周线确认清仓。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class ETHExitV2Config:
    hard_stop_atr: float = 2.0
    trailing_schedule: list[tuple[float, float]] = field(default_factory=lambda: [
        (0.0, 4.5),
        (3.0, 4.0),
        (5.0, 3.5),
        (8.0, 3.0),
        (12.0, 2.5),
    ])
    daily_exit_pct: float = 0.50
    weekly_exit_enabled: bool = True
    max_holding_days: int = 120
    pullback_tolerance_atr: float = 2.0
    pullback_max_bars: int = 7


class ETHExitV2:
    """日线信号只做部分减仓，剩余仓位等待周线趋势反转。"""

    def __init__(self, config: Optional[ETHExitV2Config] = None):
        self.config = config or ETHExitV2Config()
        self.reset()

    def reset(self) -> None:
        self.below_ma_count = 0
        self.pullback_counter = 0
        self.partial_exited = False

    def check_exit(
        self,
        position: dict,
        bar: dict,
    ) -> tuple[bool, str, float]:
        entry_price = float(position["entry_price"])
        entry_atr = float(position.get("entry_atr", bar.get("atr", entry_price * 0.02)))
        highest = float(position.get("highest_since_entry", entry_price))
        holding_days = int(position.get("holding_days", 0))
        swing_low = float(position.get("entry_swing_low", entry_price * 0.95))
        close = float(bar["close"])
        current_atr = float(bar.get("atr", entry_atr))
        profit_atr = (highest - entry_price) / entry_atr if entry_atr > 0 else 0.0

        hard_stop = entry_price - self.config.hard_stop_atr * entry_atr
        if close <= hard_stop:
            return True, "hard_stop", 1.0

        structure_break = swing_low * 0.995
        if close < structure_break:
            return True, "structure_break", 1.0

        weekly_ema20 = bar.get("weekly_ema20")
        weekly_ema50 = bar.get("weekly_ema50")
        if (
            self.config.weekly_exit_enabled
            and weekly_ema20 is not None
            and weekly_ema50 is not None
            and weekly_ema20 > 0
            and weekly_ema50 > 0
            and weekly_ema20 < weekly_ema50
        ):
            return True, "weekly_trend_reversal", 1.0

        trail_distance = self._trailing_distance(profit_atr, current_atr)
        trail_stop = highest - trail_distance
        if close < trail_stop and close > entry_price:
            pullback_atr = (highest - close) / current_atr if current_atr > 0 else 0.0
            if pullback_atr <= self.config.pullback_tolerance_atr:
                self.pullback_counter += 1
                if self.pullback_counter <= self.config.pullback_max_bars:
                    return False, "", 0.0
            else:
                self.pullback_counter = 0

            if not self.partial_exited:
                self.partial_exited = True
                return True, "trailing_partial", self.config.daily_exit_pct

            wider_stop = highest - trail_distance * 1.5
            if close < wider_stop:
                return True, "trailing_final", 1.0

        if close >= trail_stop:
            self.pullback_counter = 0

        ema20 = bar.get("ema20")
        sma50 = bar.get("sma50")
        if ema20 is not None and sma50 is not None:
            if close < ema20 < sma50:
                self.below_ma_count += 1
            else:
                self.below_ma_count = 0
            if self.below_ma_count >= 3 and holding_days > 7 and not self.partial_exited:
                self.partial_exited = True
                return True, "ma_exit_partial", self.config.daily_exit_pct

        if holding_days > self.config.max_holding_days:
            pnl_pct = (close - entry_price) / entry_price
            if pnl_pct < 0.01:
                return True, "time_stop", 1.0

        return False, "", 0.0

    def _trailing_distance(self, profit_atr: float, current_atr: float) -> float:
        multiplier = self.config.trailing_schedule[0][1]
        for threshold, schedule_multiplier in self.config.trailing_schedule:
            if profit_atr >= threshold:
                multiplier = schedule_multiplier
        return multiplier * current_atr
