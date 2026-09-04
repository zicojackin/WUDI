"""ETH 信号过滤：移除低质量 accumulation 反转，加强 Reversal 确认。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ETHFixConfig:
    forbidden_stages: set[str] = field(default_factory=lambda: {"accumulation"})
    reduced_stages: dict[str, float] = field(default_factory=lambda: {"recovery": 0.5})
    reversal_min_pattern_quality: float = 80.0
    reversal_min_setup_score: float = 55.0
    reversal_min_relative_strength: float = 70.0
    reversal_min_volume_ratio: float = 1.5
    trailing_atr_mult: float = 4.0
    max_holding_days: int = 90


class ETHFixManager:
    """在入场前过滤低质量 ETH 信号。"""

    def __init__(self, config: Optional[dataclass] = None):
        self.config = config or ETHFixConfig()

    def should_enter(
        self,
        stage: str,
        pattern: str,
        setup_score: float,
        pattern_quality: float,
        relative_strength: float,
        volume_ratio: float = 1.0,
    ) -> tuple[bool, float, str]:
        if stage in self.config.forbidden_stages:
            return False, 0.0, f"stage {stage} forbidden"

        position_multiplier = self.config.reduced_stages.get(stage, 1.0)

        if stage == "reversal_extension":
            if pattern_quality < self.config.reversal_min_pattern_quality:
                return False, 0.0, "reversal pattern quality too low"
            if setup_score < self.config.reversal_min_setup_score:
                return False, 0.0, "reversal setup score too low"
            if relative_strength < self.config.reversal_min_relative_strength:
                return False, 0.0, "reversal relative strength too low"
            if volume_ratio < self.config.reversal_min_volume_ratio:
                return False, 0.0, "reversal volume too low"

        return True, position_multiplier, "passed"

    def exit_params(self) -> dict:
        return {
            "trailing_atr_mult": self.config.trailing_atr_mult,
            "max_holding_days": self.config.max_holding_days,
        }
