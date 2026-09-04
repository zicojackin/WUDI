"""ETH V3: trend-following base layer with a strict exception add-on."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(slots=True)
class ETHStrategyV3Config:
    """Configuration for the simplified ETH strategy."""

    base_position_pct: float = 0.20
    sma200_buffer: float = 0.97
    signal_layer_enabled: bool = False

    exception_enabled: bool = True
    exception_min_setup_score: float = 85.0
    exception_min_pattern_quality: float = 85.0
    exception_position_pct: float = 0.05
    exception_max_per_year: int = 2


@dataclass(slots=True)
class ETHStrategyV3Action:
    base_action: Optional[str] = None
    exception_action: Optional[str] = None
    target_exposure: float = 0.0
    reason: str = ""


class ETHStrategyV3:
    """Keep ETH exposure through the trend, but ignore ordinary entry signals."""

    def __init__(self, config: Optional[ETHStrategyV3Config] = None):
        self.config = config or ETHStrategyV3Config()
        self.base_open = False
        self.exception_open = False
        self.current_year: Optional[int] = None
        self.exception_count_this_year = 0
        self._last_action: Optional[ETHStrategyV3Action] = None
        self.entry_price: float = 0.0
        self.entry_date: Optional[pd.Timestamp] = None

    def on_bar(self, bar: dict, weekly_bar: Optional[dict]) -> ETHStrategyV3Action:
        result = ETHStrategyV3Action()
        if weekly_bar is None:
            return result

        self._update_year(bar)
        weekly_up = self._weekly_up(weekly_bar)
        above_sma200 = self._above_sma200(bar)

        if self.base_open and (not weekly_up or not above_sma200):
            self.base_open = False
            self.exception_open = False
            result.base_action = "close"
            result.reason = "weekly_down_or_below_sma200"
        elif not self.base_open and weekly_up and above_sma200:
            self.base_open = True
            self.entry_price = float(bar["close"])
            self.entry_date = bar.get("date")
            result.base_action = "open"
            result.reason = "weekly_up_and_above_sma200"

        if (
            self.config.exception_enabled
            and self.base_open
            and not self.exception_open
            and self.exception_count_this_year < self.config.exception_max_per_year
        ):
            setup_score = float(bar.get("setup_score", 0.0))
            pattern_quality = float(bar.get("pattern_quality", 0.0))
            if (
                setup_score >= self.config.exception_min_setup_score
                and pattern_quality >= self.config.exception_min_pattern_quality
            ):
                self.exception_open = True
                self.exception_count_this_year += 1
                result.exception_action = "add"

        if self.base_open:
            result.target_exposure = self.config.base_position_pct
            if self.exception_open:
                result.target_exposure += self.config.exception_position_pct

        self._last_action = result
        return result

    def reset(self) -> None:
        self.base_open = False
        self.exception_open = False
        self.current_year = None
        self.exception_count_this_year = 0
        self._last_action = None
        self.entry_price = 0.0
        self.entry_date = None

    @property
    def target_exposure(self) -> float:
        if not self.base_open:
            return 0.0
        if self.exception_open:
            return self.config.base_position_pct + self.config.exception_position_pct
        return self.config.base_position_pct

    def summary(self) -> str:
        exception = (
            "enabled"
            if self.config.exception_enabled
            else "disabled"
        )
        return (
            "ETH V3 strategy\n"
            f"  mode: base layer only (signal layer disabled={not self.config.signal_layer_enabled})\n"
            f"  base exposure: {self.config.base_position_pct:.0%}\n"
            f"  exception: {exception}, +{self.config.exception_position_pct:.0%}, "
            f"max {self.config.exception_max_per_year}/year"
        )

    def _update_year(self, bar: dict) -> None:
        date = bar.get("date")
        year = date.year if isinstance(date, pd.Timestamp) else None
        if year is None:
            year = pd.Timestamp.now().year
        if year != self.current_year:
            self.current_year = year
            self.exception_count_this_year = 0

    @staticmethod
    def _weekly_up(weekly_bar: dict) -> bool:
        ema20 = float(weekly_bar.get("ema20", 0.0))
        ema50 = float(weekly_bar.get("ema50", 0.0))
        return ema20 > 0 and ema50 > 0 and ema20 > ema50

    def _above_sma200(self, bar: dict) -> bool:
        sma200 = float(bar.get("sma200", 0.0))
        close = float(bar["close"])
        return sma200 > 0 and close > sma200 * self.config.sma200_buffer
