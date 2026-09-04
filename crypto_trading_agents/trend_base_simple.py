"""简化趋势底仓：周线向上且价格在 SMA200 上方时保持底仓。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(slots=True)
class TrendBaseState:
    is_open: bool = False
    entry_price: float = 0.0
    entry_date: Optional[pd.Timestamp] = None
    size: float = 0.0
    highest_since_entry: float = 0.0
    holding_days: int = 0


class TrendBaseSimple:
    """极简双层结构中的趋势底仓层。"""

    def __init__(
        self,
        position_pct: float = 0.15,
        trailing_atr_mult: float = 5.0,
        sma200_buffer: float = 0.97,
    ):
        self.position_pct = position_pct
        self.trailing_atr_mult = trailing_atr_mult
        self.sma200_buffer = sma200_buffer
        self.state = TrendBaseState()

    def on_bar(self, bar: dict, weekly_bar: Optional[dict]) -> Optional[str]:
        if weekly_bar is None:
            return None

        if self.state.is_open:
            if self._should_exit(bar, weekly_bar):
                self.state.is_open = False
                return "close"
            self.state.holding_days += 1
            self.state.highest_since_entry = max(
                self.state.highest_since_entry,
                float(bar.get("high", bar["close"])),
            )
            return None

        if self._should_enter(bar, weekly_bar):
            close = float(bar["close"])
            self.state.is_open = True
            self.state.entry_price = close
            self.state.entry_date = pd.Timestamp(bar.get("date", pd.Timestamp.now()))
            self.state.highest_since_entry = close
            self.state.holding_days = 0
            return "open"
        return None

    def _should_enter(self, bar: dict, weekly_bar: dict) -> bool:
        weekly_ema20 = float(weekly_bar.get("ema20", 0.0))
        weekly_ema50 = float(weekly_bar.get("ema50", 0.0))
        sma200 = float(bar.get("sma200", 0.0))
        close = float(bar["close"])
        return (
            weekly_ema20 > 0
            and weekly_ema50 > 0
            and sma200 > 0
            and weekly_ema20 > weekly_ema50
            and close > sma200
        )

    def _should_exit(self, bar: dict, weekly_bar: dict) -> bool:
        weekly_ema20 = float(weekly_bar.get("ema20", 0.0))
        weekly_ema50 = float(weekly_bar.get("ema50", 0.0))
        sma200 = float(bar.get("sma200", 0.0))
        close = float(bar["close"])
        atr = float(bar.get("atr", close * 0.02))
        if weekly_ema20 > 0 and weekly_ema50 > 0 and weekly_ema20 < weekly_ema50:
            return True
        if sma200 > 0 and close < sma200 * self.sma200_buffer:
            return True
        trailing_stop = self.state.highest_since_entry - self.trailing_atr_mult * atr
        return close < trailing_stop

    def position_size(self, account_equity: float, current_price: float) -> float:
        notional = account_equity * self.position_pct
        return notional / current_price if current_price > 0 else 0.0

    @property
    def exposure(self) -> float:
        return self.position_pct if self.state.is_open else 0.0


def weekly_frame_from_daily(frame: pd.DataFrame) -> pd.DataFrame:
    """把日线重采样为周线，供趋势底仓使用。"""
    indexed = frame.copy()
    indexed["date"] = pd.to_datetime(indexed["date"])
    indexed = indexed.set_index("date")
    weekly = indexed.resample("W-MON").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    weekly["ema20"] = weekly["close"].ewm(span=20, adjust=False).mean()
    weekly["ema50"] = weekly["close"].ewm(span=50, adjust=False).mean()
    return weekly
