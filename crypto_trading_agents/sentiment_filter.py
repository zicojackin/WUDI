"""情绪辅助过滤模块：Fear & Greed 和资金费率情绪。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


@dataclass(slots=True)
class SentimentConfig:
    extreme_fear_threshold: int = 20
    fear_threshold: int = 35
    greed_threshold: int = 65
    extreme_greed_threshold: int = 80
    position_multipliers: dict[str, float] = field(default_factory=lambda: {
        "extreme_fear": 1.3,
        "fear": 1.15,
        "neutral": 1.0,
        "greed": 0.8,
        "extreme_greed": 0.6,
    })
    funding_extreme_positive: float = 0.001
    funding_extreme_negative: float = -0.0005
    use_fear_greed: bool = True
    use_funding_sentiment: bool = True
    use_contrarian_mode: bool = True


class FearGreedFetcher:
    """获取 alternative.me 的 Fear & Greed 历史 Index。"""

    API_URL = "https://api.alternative.me/fng/"
    CACHE_FILE = Path("data/sentiment/fear_greed_cache.csv")

    def __init__(self, use_cache: bool = True):
        self.use_cache = use_cache
        self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    def fetch(self, days: int = 730) -> pd.Series:
        if self.use_cache and self.CACHE_FILE.exists():
            cached = self._load_cache()
            if cached is not None and len(cached) >= days * 0.9:
                return cached
        if not HAS_REQUESTS:
            return self._default_series(days)

        records: list[dict] = []
        remaining = days
        while remaining > 0:
            limit = min(remaining, 365)
            response = requests.get(self.API_URL, params={"limit": limit}, timeout=10)
            response.raise_for_status()
            batch = response.json().get("data", [])
            if not batch:
                break
            records.extend(batch)
            remaining -= len(batch)
            if len(batch) < limit:
                break

        if not records:
            return self._default_series(days)

        frame = pd.DataFrame(records)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"].astype(int), unit="s")
        frame["value"] = frame["value"].astype(int)
        series = frame.set_index("timestamp")["value"].sort_index()
        series = series[~series.index.duplicated(keep="first")]
        if self.use_cache:
            self._save_cache(series)
        return series

    def _default_series(self, days: int) -> pd.Series:
        return pd.Series(50, index=pd.date_range(end=pd.Timestamp.now(), periods=days, freq="1D"), name="value")

    def _load_cache(self) -> Optional[pd.Series]:
        try:
            frame = pd.read_csv(self.CACHE_FILE, index_col=0, parse_dates=True)
            return frame.iloc[:, 0]
        except Exception:
            return None

    def _save_cache(self, series: pd.Series) -> None:
        try:
            series.to_csv(self.CACHE_FILE, header=["value"])
        except Exception:
            pass


class SentimentFilter:
    """把情绪转化为仓位乘数和信号调整，不直接生成方向。"""

    def __init__(self, config: Optional[SentimentConfig] = None):
        self.config = config or SentimentConfig()
        self.fear_greed_data: Optional[pd.Series] = None

    def load_data(self, days: int = 730) -> None:
        self.fear_greed_data = FearGreedFetcher().fetch(days)

    def load_series(self, series: pd.Series) -> None:
        self.fear_greed_data = series

    def _latest(self, date: pd.Timestamp) -> Optional[int]:
        if self.fear_greed_data is None:
            return None
        available = self.fear_greed_data[self.fear_greed_data.index <= date]
        return int(available.iloc[-1]) if len(available) else None

    def get_position_multiplier(self, date: pd.Timestamp) -> float:
        if not self.config.use_fear_greed:
            return 1.0
        value = self._latest(date)
        if value is None:
            return 1.0
        return float(
            self.config.position_multipliers.get(
                self._classify_sentiment(value),
                1.0,
            )
        )

    def get_signal_adjustment(self, date: pd.Timestamp) -> float:
        value = self._latest(date)
        if value is None:
            return 0.0
        if value <= self.config.extreme_fear_threshold:
            return 15.0
        if value <= self.config.fear_threshold:
            return 8.0
        if value >= self.config.extreme_greed_threshold:
            return -15.0
        if value >= self.config.greed_threshold:
            return -8.0
        return 0.0

    def should_skip_entry(self, date: pd.Timestamp) -> tuple[bool, str]:
        value = self._latest(date)
        if value is not None and value >= 90:
            return True, f"Fear & Greed = {value}, skip long entry"
        return False, ""

    def get_funding_sentiment(self, funding_rate: float) -> tuple[str, float]:
        if not self.config.use_funding_sentiment:
            return "neutral", 1.0
        if funding_rate > self.config.funding_extreme_positive:
            return "overly_optimistic", 0.7
        if funding_rate < self.config.funding_extreme_negative:
            return "overly_pessimistic", 1.2
        return "neutral", 1.0

    def get_combined_multiplier(
        self,
        date: pd.Timestamp,
        funding_rate: Optional[float] = None,
    ) -> float:
        fear_greed_multiplier = self.get_position_multiplier(date)
        funding_multiplier = 1.0
        if funding_rate is not None:
            _, funding_multiplier = self.get_funding_sentiment(funding_rate)
        combined = fear_greed_multiplier * 0.7 + funding_multiplier * 0.3
        return max(0.5, min(1.5, combined))

    def _classify_sentiment(self, value: int) -> str:
        if value <= self.config.extreme_fear_threshold:
            return "extreme_fear"
        if value <= self.config.fear_threshold:
            return "fear"
        if value >= self.config.extreme_greed_threshold:
            return "extreme_greed"
        if value >= self.config.greed_threshold:
            return "greed"
        return "neutral"
