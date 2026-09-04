"""出场优化器：阶梯跟踪、回调容忍、连续均线确认。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass(slots=True)
class ExitOptimizerConfig:
    trailing_schedule: list[tuple[float, float]] = field(default_factory=lambda: [
        (0.0, 4.0),
        (2.0, 3.5),
        (4.0, 3.0),
        (6.0, 2.5),
        (10.0, 2.0),
    ])
    pullback_tolerance_atr: float = 1.5
    pullback_max_bars: int = 5
    ma_exit_consecutive_days: int = 3
    time_stop_only_when_loss: bool = True
    hard_stop_atr_mult: float = 2.0
    structure_break_buffer: float = 0.005
    time_stop_days: int = 60


class ExitOptimizer:
    """根据盈利幅度放宽跟踪距离，并容忍趋势中的正常回调。"""

    def __init__(self, config: Optional[ExitOptimizerConfig] = None):
        self.config = config or ExitOptimizerConfig()
        self.reset()

    def reset(self) -> None:
        self.pullback_counter = 0
        self.below_ma_count = 0

    def should_exit(
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
        current_pnl_pct = (close - entry_price) / entry_price

        hard_stop = entry_price - self.config.hard_stop_atr_mult * entry_atr
        if close <= hard_stop:
            return True, "hard_stop", 1.0

        structure_break = swing_low * (1 - self.config.structure_break_buffer)
        if close < structure_break:
            return True, "structure_break", 1.0

        trailing_distance = self._trailing_distance(profit_atr, current_atr)
        trailing_stop = highest - trailing_distance
        if close < trailing_stop and close > entry_price:
            if self._is_acceptable_pullback(position, bar):
                self.pullback_counter += 1
                if self.pullback_counter <= self.config.pullback_max_bars:
                    return False, "", 0.0
            else:
                self.pullback_counter = 0
            return True, f"trailing_stop ({profit_atr:.1f} ATR)", 1.0
        if close >= trailing_stop:
            self.pullback_counter = 0

        ema20 = bar.get("ema20")
        sma50 = bar.get("sma50")
        if ema20 is not None and sma50 is not None:
            if close < ema20 < sma50:
                self.below_ma_count += 1
            else:
                self.below_ma_count = 0
            if (
                self.below_ma_count >= self.config.ma_exit_consecutive_days
                and holding_days > 7
            ):
                return True, f"ma_exit ({self.below_ma_count} days)", 0.75

        if holding_days > self.config.time_stop_days:
            threshold = 0.01 if self.config.time_stop_only_when_loss else 0.02
            if current_pnl_pct < threshold:
                return True, f"time_stop ({holding_days} days)", 1.0

        return False, "", 0.0

    def _trailing_distance(self, profit_atr: float, current_atr: float) -> float:
        multiplier = self.config.trailing_schedule[0][1]
        for threshold, schedule_multiplier in self.config.trailing_schedule:
            if profit_atr >= threshold:
                multiplier = schedule_multiplier
        return multiplier * current_atr

    def _is_acceptable_pullback(self, position: dict, bar: dict) -> bool:
        close = float(bar["close"])
        atr = float(bar.get("atr", position.get("entry_atr", close * 0.02)))
        highest = float(position.get("highest_since_entry", close))
        pullback_atr = (highest - close) / atr if atr > 0 else 0.0
        if pullback_atr <= self.config.pullback_tolerance_atr:
            return True
        ema20 = bar.get("ema20")
        return ema20 is not None and close > ema20


def create_btc_exit_optimizer() -> ExitOptimizer:
    """BTC 趋势更持久，跟踪和回调容忍都更宽。"""
    return ExitOptimizer(
        ExitOptimizerConfig(
            trailing_schedule=[
                (0.0, 4.5),
                (2.0, 4.0),
                (4.0, 3.5),
                (6.0, 3.0),
                (10.0, 2.5),
                (15.0, 2.0),
            ],
            pullback_tolerance_atr=2.0,
            pullback_max_bars=7,
        )
    )


def create_eth_exit_optimizer() -> ExitOptimizer:
    """ETH 跟踪比 BTC 稍紧，但比原 3 ATR 宽。"""
    return ExitOptimizer(
        ExitOptimizerConfig(
            trailing_schedule=[
                (0.0, 4.0),
                (2.0, 3.5),
                (4.0, 3.0),
                (6.0, 2.5),
                (10.0, 2.0),
            ],
            pullback_tolerance_atr=1.5,
            pullback_max_bars=5,
        )
    )
