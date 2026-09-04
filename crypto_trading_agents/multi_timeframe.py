"""多时间框架入场模块：日线准备信号，4H 战术触发。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd


class MTFSignalState(str, Enum):
    IDLE = "idle"
    WAITING_4H = "waiting_4h"
    ENTERED = "entered"
    EXPIRED = "expired"


@dataclass(slots=True)
class MTFConfig:
    daily_signal_min_score: float = 50.0
    daily_signal_phases: set[str] = field(
        default_factory=lambda: {
            "reversal_extension",
            "base_n_break",
            "ema_crossback",
            "accumulation",
            "recovery",
            "markup",
        }
    )
    h4_max_wait_bars: int = 18
    h4_pullback_atr_mult: float = 1.5
    h4_min_volume_ratio: float = 0.8
    h4_structure_confirm: bool = True
    entry_mode: str = "pullback"


@dataclass(slots=True)
class DailySignal:
    date: pd.Timestamp
    setup_score: float
    pattern_quality: float
    cycle_phase: str
    entry_price_ref: float
    swing_low: float
    atr: float
    direction: str = "long"


@dataclass(slots=True)
class H4EntryTrigger:
    timestamp: pd.Timestamp
    price: float
    trigger_type: str
    volume_ratio: float
    structure_intact: bool
    confidence: float


class MultiTimeframeEntry:
    """维护日线准备信号，并在后续 4H K 线中寻找战术触发。"""

    def __init__(self, config: Optional[MTFConfig] = None):
        self.config = config or MTFConfig()
        self.reset()

    def reset(self) -> None:
        self.state = MTFSignalState.IDLE
        self.pending_signal: Optional[DailySignal] = None
        self.wait_count = 0
        self.h4_bars_since_signal: list[dict] = []

    def on_daily_bar(self, bar: dict, signal_score: float) -> Optional[DailySignal]:
        if self.state == MTFSignalState.ENTERED:
            return None
        cycle_phase = str(bar.get("cycle_phase", ""))
        if cycle_phase not in self.config.daily_signal_phases:
            return None
        if signal_score < self.config.daily_signal_min_score:
            return None

        close = float(bar["close"])
        self.pending_signal = DailySignal(
            date=pd.Timestamp(bar.get("date", pd.Timestamp.now())),
            setup_score=float(bar.get("setup_score", 0.0)),
            pattern_quality=float(bar.get("pattern_quality", 0.0)),
            cycle_phase=cycle_phase,
            entry_price_ref=close,
            swing_low=float(bar.get("swing_low", bar.get("low", close))),
            atr=float(bar.get("atr", close * 0.02)),
        )
        self.state = MTFSignalState.WAITING_4H
        self.wait_count = 0
        self.h4_bars_since_signal = []
        return self.pending_signal

    def on_4h_bar(self, bar: dict) -> Optional[H4EntryTrigger]:
        if self.state != MTFSignalState.WAITING_4H or self.pending_signal is None:
            return None

        self.wait_count += 1
        self.h4_bars_since_signal.append(bar)
        if self.wait_count > self.config.h4_max_wait_bars:
            self.reset()
            return None

        trigger = None
        if self.config.entry_mode in {"pullback", "both"}:
            trigger = self._check_pullback_entry(bar)
        if trigger is None and self.config.entry_mode in {"breakout", "both"}:
            trigger = self._check_breakout_entry(bar)

        if trigger is not None:
            self.state = MTFSignalState.ENTERED
        return trigger

    def _check_pullback_entry(self, bar: dict) -> Optional[H4EntryTrigger]:
        signal = self.pending_signal
        if signal is None:
            return None

        close = float(bar["close"])
        low = float(bar["low"])
        atr = float(bar.get("atr", close * 0.01))
        zone_low = signal.entry_price_ref - self.config.h4_pullback_atr_mult * signal.atr
        zone_high = signal.entry_price_ref + 0.5 * signal.atr
        if not zone_low <= low <= zone_high:
            return None

        body = abs(close - float(bar.get("open", close)))
        lower_shadow = min(close, float(bar.get("open", close))) - low
        has_rejection = lower_shadow > body * 1.5 if body > 0 else lower_shadow > atr * 0.5
        if not has_rejection:
            return None

        volume_ratio = self._volume_ratio(bar)
        if volume_ratio < self.config.h4_min_volume_ratio:
            return None
        if self.config.h4_structure_confirm and close < signal.swing_low:
            return None

        return H4EntryTrigger(
            timestamp=pd.Timestamp(bar.get("timestamp", pd.Timestamp.now())),
            price=close,
            trigger_type="pullback_bounce",
            volume_ratio=volume_ratio,
            structure_intact=True,
            confidence=self._confidence(bar, signal, "pullback_bounce", volume_ratio),
        )

    def _check_breakout_entry(self, bar: dict) -> Optional[H4EntryTrigger]:
        signal = self.pending_signal
        if signal is None or len(self.h4_bars_since_signal) < 6:
            return None

        close = float(bar["close"])
        volume_ratio = self._volume_ratio(bar)
        if volume_ratio < 1.5:
            return None
        recent_high = max(
            float(item.get("high", item.get("close", close)))
            for item in self.h4_bars_since_signal[:-1]
        )
        if close <= recent_high:
            return None
        if self.config.h4_structure_confirm and close < signal.swing_low:
            return None

        return H4EntryTrigger(
            timestamp=pd.Timestamp(bar.get("timestamp", pd.Timestamp.now())),
            price=close,
            trigger_type="breakout",
            volume_ratio=volume_ratio,
            structure_intact=True,
            confidence=self._confidence(bar, signal, "breakout", volume_ratio),
        )

    def _volume_ratio(self, bar: dict) -> float:
        volume_ma = float(bar.get("volume_ma", 0.0))
        return float(bar.get("volume", 0.0)) / volume_ma if volume_ma > 0 else 1.0

    def _confidence(
        self,
        bar: dict,
        signal: DailySignal,
        trigger_type: str,
        volume_ratio: float,
    ) -> float:
        close = float(bar["close"])
        score = 50.0
        score += (signal.setup_score - 50.0) * 0.3
        score += min(volume_ratio * 10.0, 20.0)
        if close > float(bar.get("ema20", close)):
            score += 10.0
        if trigger_type == "pullback_bounce":
            score += 5.0
        elif trigger_type == "breakout":
            score -= 5.0
        return max(0.0, min(100.0, score))

    def get_state(self) -> dict:
        return {
            "state": self.state.value,
            "wait_count": self.wait_count,
            "has_pending_signal": self.pending_signal is not None,
            "signal_date": self.pending_signal.date if self.pending_signal else None,
        }
