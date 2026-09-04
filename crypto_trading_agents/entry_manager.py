"""分层入场管理模块：A/B/C 级信号和动态仓位。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EntryTier(str, Enum):
    """入场等级。"""

    A = "A"
    B = "B"
    C = "C"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class EntryCriteria:
    """单级入场门槛。"""

    min_setup_score: float
    min_pattern_quality: float
    position_pct: float
    description: str = ""


@dataclass(slots=True)
class EntryProfile:
    """入场参数。"""

    tier_a: EntryCriteria = field(
        default_factory=lambda: EntryCriteria(
            75.0, 70.0, 1.0, "高质量信号，满仓"
        )
    )
    tier_b: EntryCriteria = field(
        default_factory=lambda: EntryCriteria(
            60.0, 50.0, 0.7, "中等信号，70% 仓位"
        )
    )
    tier_c: EntryCriteria = field(
        default_factory=lambda: EntryCriteria(
            45.0, 35.0, 0.4, "低质量信号，40% 仓位"
        )
    )
    factor_weights: dict[str, float] = field(
        default_factory=lambda: {
            "pattern": 0.30,
            "volume": 0.15,
            "structure": 0.20,
            "relative_strength": 0.15,
            "phase": 0.10,
            "weekly_trend": 0.10,
        }
    )
    use_weekly_trend_bonus: bool = True
    use_volume_confirmation: bool = True
    volume_full_score_ratio: float = 2.0
    allowed_phases: set[str] = field(
        default_factory=lambda: {
            "accumulation",
            "recovery",
            "markup",
            "reversal_extension",
            "wedge_pop",
            "ema_crossback",
            "base_n_break",
        }
    )


class EntryManager:
    """评估 A/B/C 级入场信号并返回建议仓位。"""

    def __init__(self, profile: Optional[EntryProfile] = None):
        self.profile = profile or EntryProfile()

    def evaluate_entry(self, bar: dict, weekly_bar: Optional[dict] = None) -> tuple[EntryTier, float, dict]:
        """评估单根 K 线的入场等级。"""
        cycle_phase = str(bar.get("cycle_phase", bar.get("cycle_state", bar.get("stage", ""))))
        if cycle_phase not in self.profile.allowed_phases:
            return EntryTier.SKIP, 0.0, {"reason": f"phase {cycle_phase} not allowed"}

        factor_scores = self._factor_scores(bar, weekly_bar, cycle_phase)
        composite_score = self._weighted_composite(factor_scores)
        tier = self._classify_tier(
            setup_score=float(bar.get("setup_score", 0.0)),
            pattern_quality=float(bar.get("pattern_quality", 0.0)),
        )
        position_pct = self._position_pct(tier)
        return tier, position_pct, {
            "composite_score": composite_score,
            "factor_scores": factor_scores,
            "tier": tier.value,
            "position_pct": position_pct,
            "cycle_phase": cycle_phase,
        }

    def _factor_scores(
        self,
        bar: dict,
        weekly_bar: Optional[dict],
        cycle_phase: str,
    ) -> dict[str, float]:
        volume = float(bar.get("volume", 0.0))
        volume_ma = float(bar.get("volume_ma", bar.get("volume_ma20", 0.0)))
        if self.profile.use_volume_confirmation and volume_ma > 0:
            volume_ratio = volume / volume_ma
            volume_score = min(volume_ratio / self.profile.volume_full_score_ratio * 100, 100.0)
        else:
            volume_score = 50.0

        if self.profile.use_weekly_trend_bonus and weekly_bar:
            weekly_score = self._weekly_trend_score(weekly_bar)
        else:
            weekly_score = 50.0

        return {
            "pattern": float(bar.get("pattern_quality", 0.0)),
            "volume": volume_score,
            "structure": float(bar.get("structure_score", bar.get("quality_swing", 50.0))),
            "relative_strength": float(bar.get("relative_strength_score", 50.0)),
            "phase": self._phase_confidence(cycle_phase),
            "weekly_trend": weekly_score,
        }

    def _weighted_composite(self, factor_scores: dict[str, float]) -> float:
        total_weight = sum(self.profile.factor_weights.values())
        weighted_sum = sum(
            factor_scores.get(name, 0.0) * weight
            for name, weight in self.profile.factor_weights.items()
        )
        return weighted_sum / total_weight if total_weight else 0.0

    def _classify_tier(self, setup_score: float, pattern_quality: float) -> EntryTier:
        if (
            setup_score >= self.profile.tier_a.min_setup_score
            and pattern_quality >= self.profile.tier_a.min_pattern_quality
        ):
            return EntryTier.A
        if (
            setup_score >= self.profile.tier_b.min_setup_score
            and pattern_quality >= self.profile.tier_b.min_pattern_quality
        ):
            return EntryTier.B
        if (
            setup_score >= self.profile.tier_c.min_setup_score
            and pattern_quality >= self.profile.tier_c.min_pattern_quality
        ):
            return EntryTier.C
        return EntryTier.SKIP

    def _position_pct(self, tier: EntryTier) -> float:
        if tier == EntryTier.A:
            return self.profile.tier_a.position_pct
        if tier == EntryTier.B:
            return self.profile.tier_b.position_pct
        if tier == EntryTier.C:
            return self.profile.tier_c.position_pct
        return 0.0

    def _phase_confidence(self, phase: str) -> float:
        phase_scores = {
            "reversal_extension": 85,
            "base_n_break": 80,
            "ema_crossback": 75,
            "wedge_pop": 70,
            "accumulation": 65,
            "recovery": 60,
            "markup": 55,
            "distribution": 20,
            "markdown": 10,
            "exhaustion_extension": 15,
            "wedge_drop": 10,
            "ema_crossback_downside": 10,
            "base_n_break_downside": 10,
        }
        return float(phase_scores.get(phase, 30))

    def _weekly_trend_score(self, weekly_bar: dict) -> float:
        close = float(weekly_bar.get("close", 0.0))
        ema20 = float(weekly_bar.get("ema20", close))
        ema50 = float(weekly_bar.get("ema50", close))
        if close > ema20 > ema50:
            return 90.0
        if close > ema20:
            return 70.0
        if close > ema50:
            return 50.0
        return 25.0


def create_btc_entry_profile() -> EntryProfile:
    """BTC 入场配置。"""
    return EntryProfile()


def create_eth_entry_profile() -> EntryProfile:
    """ETH 入场配置，C 级门槛略宽。"""
    return EntryProfile(
        tier_a=EntryCriteria(70.0, 65.0, 1.0),
        tier_b=EntryCriteria(55.0, 45.0, 0.7),
        tier_c=EntryCriteria(40.0, 30.0, 0.4),
    )
