"""自适应出场模块：根据波动率状态和趋势强度调整出场参数。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd


class MarketRegime(str, Enum):
    HIGH_VOL_TREND = "high_vol_trend"
    HIGH_VOL_RANGE = "high_vol_range"
    LOW_VOL_TREND = "low_vol_trend"
    LOW_VOL_RANGE = "low_vol_range"


@dataclass(slots=True)
class AdaptiveExitConfig:
    vol_lookback: int = 20
    vol_percentile_high: float = 70.0
    vol_percentile_low: float = 30.0
    trend_lookback: int = 20
    adx_threshold: float = 25.0
    regime_params: dict[str, dict] = field(default_factory=lambda: {
        MarketRegime.HIGH_VOL_TREND.value: {
            "hard_stop_atr": 3.0,
            "trailing_atr": 4.0,
            "partial_tp_atr": 5.0,
            "time_stop_days": 90,
            "ma_exit_enabled": False,
        },
        MarketRegime.HIGH_VOL_RANGE.value: {
            "hard_stop_atr": 2.0,
            "trailing_atr": 2.5,
            "partial_tp_atr": 3.0,
            "time_stop_days": 30,
            "ma_exit_enabled": True,
        },
        MarketRegime.LOW_VOL_TREND.value: {
            "hard_stop_atr": 2.5,
            "trailing_atr": 3.0,
            "partial_tp_atr": 4.0,
            "time_stop_days": 60,
            "ma_exit_enabled": True,
        },
        MarketRegime.LOW_VOL_RANGE.value: {
            "hard_stop_atr": 1.5,
            "trailing_atr": 2.0,
            "partial_tp_atr": 2.5,
            "time_stop_days": 20,
            "ma_exit_enabled": True,
        },
    })


class MarketRegimeDetector:
    """用归一化 ATR 百分位和简化 ADX 判断市场状态。"""

    def __init__(self, config: Optional[AdaptiveExitConfig] = None):
        self.config = config or AdaptiveExitConfig()

    def detect(self, frame: pd.DataFrame, index: int) -> MarketRegime:
        minimum = max(self.config.vol_lookback, self.config.trend_lookback) + 5
        if index < minimum:
            return MarketRegime.LOW_VOL_RANGE

        volatility_percentile = self._volatility_percentile(frame, index)
        trend_strength = self._trend_strength(frame, index)
        high_vol = volatility_percentile >= self.config.vol_percentile_high
        low_vol = volatility_percentile <= self.config.vol_percentile_low
        trending = trend_strength >= self.config.adx_threshold

        if high_vol and trending:
            return MarketRegime.HIGH_VOL_TREND
        if high_vol:
            return MarketRegime.HIGH_VOL_RANGE
        if trending:
            return MarketRegime.LOW_VOL_TREND
        return MarketRegime.LOW_VOL_RANGE

    def get_params(self, regime: MarketRegime) -> dict:
        return self.config.regime_params[regime.value]

    def _true_range(self, frame: pd.DataFrame, end: int) -> pd.Series:
        high = frame["high"].iloc[: end + 1]
        low = frame["low"].iloc[: end + 1]
        close = frame["close"].iloc[: end + 1]
        return pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)

    def _volatility_percentile(self, frame: pd.DataFrame, index: int) -> float:
        true_range = self._true_range(frame, index)
        normalized = (true_range.rolling(14).mean() / frame["close"].iloc[: index + 1]).dropna()
        if len(normalized) < self.config.vol_lookback + 1:
            return 50.0
        current = normalized.iloc[-1]
        historical = normalized.iloc[-self.config.vol_lookback - 1 : -1]
        return float((historical < current).mean() * 100.0)

    def _trend_strength(self, frame: pd.DataFrame, index: int) -> float:
        lookback = self.config.trend_lookback
        if index < lookback + 1:
            return 0.0
        start = index - lookback
        high = frame["high"].iloc[start : index + 1]
        low = frame["low"].iloc[start : index + 1]
        close = frame["close"].iloc[start : index + 1]
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = pd.Series(
            np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
            index=high.index,
        )
        minus_dm = pd.Series(
            np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
            index=high.index,
        )
        true_range = self._true_range(frame, index).iloc[start :]
        atr = true_range.rolling(14).mean()
        plus_di = 100.0 * plus_dm.rolling(14).mean() / (atr + 1e-10)
        minus_di = 100.0 * minus_dm.rolling(14).mean() / (atr + 1e-10)
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
        return float(dx.iloc[-1]) if len(dx) else 0.0


class AdaptiveExitManager:
    """根据市场状态返回出场信号。"""

    def __init__(self, config: Optional[AdaptiveExitConfig] = None):
        self.config = config or AdaptiveExitConfig()
        self.detector = MarketRegimeDetector(self.config)

    def detect_regime(self, frame: pd.DataFrame, index: int) -> MarketRegime:
        return self.detector.detect(frame, index)

    def check_exit(
        self,
        position: dict,
        bar: dict,
        regime: MarketRegime,
    ) -> Optional[dict]:
        params = self.detector.get_params(regime)
        entry_price = float(position["entry_price"])
        entry_atr = float(position.get("entry_atr", bar.get("atr", entry_price * 0.02)))
        highest = float(position.get("highest_since_entry", entry_price))
        holding_days = int(position.get("holding_days", 0))
        swing_low = float(position.get("entry_swing_low", entry_price * 0.95))
        current_atr = float(bar.get("atr", entry_atr))
        close = float(bar["close"])

        hard_stop = entry_price - params["hard_stop_atr"] * entry_atr
        if close <= hard_stop:
            return self._signal("adaptive_hard_stop", regime, close)
        if close < swing_low * 0.995:
            return self._signal("structure_break", regime, close)

        trailing_stop = highest - params["trailing_atr"] * current_atr
        if close < trailing_stop and close > entry_price:
            return self._signal("adaptive_trailing", regime, close)

        if current_atr > 0:
            profit_atr = (close - entry_price) / current_atr
            if profit_atr >= params["partial_tp_atr"]:
                return {**self._signal("adaptive_partial_tp", regime, close), "exit_pct": 0.5}

        if params.get("ma_exit_enabled", True) and holding_days > 5:
            ema20 = bar.get("ema20")
            sma50 = bar.get("sma50")
            if ema20 is not None and sma50 is not None and close < ema20 < sma50:
                return {**self._signal("ma_exit", regime, close), "exit_pct": 0.75}

        if holding_days > params["time_stop_days"]:
            pnl_pct = (close - entry_price) / entry_price
            if pnl_pct < 0.02:
                return self._signal("time_stop", regime, close)
        return None

    def _signal(self, reason: str, regime: MarketRegime, price: float) -> dict:
        return {
            "reason": f"{reason} ({regime.value})",
            "exit_pct": 1.0,
            "price": price,
            "regime": regime.value,
        }
