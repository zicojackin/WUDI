"""出场管理模块：结构破位、均线出场、时间止损和阶梯移动止损。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExitReason(str, Enum):
    """出场原因。"""

    HARD_STOP = "hard_stop"
    STRUCTURE_BREAK = "structure_break"
    MA_EXIT = "ma_exit"
    TIME_STOP = "time_stop"
    TRAILING_STOP = "trailing_stop"
    PARTIAL_TAKE_PROFIT = "partial_tp"
    MANUAL = "manual"


@dataclass(slots=True)
class ExitSignal:
    """单次出场信号。"""

    reason: ExitReason
    exit_pct: float
    price: float
    description: str = ""


@dataclass(slots=True)
class PositionState:
    """出场管理需要的持仓状态。"""

    entry_price: float
    entry_date: object
    entry_swing_low: float
    entry_atr: float
    highest_since_entry: float
    current_size: float
    initial_size: float
    holding_days: int = 0
    completed_partial_exits: set[int] = field(default_factory=set)
    stop_price: float = 0.0


@dataclass(slots=True)
class ExitProfile:
    """出场参数。"""

    hard_stop_atr_mult: float = 2.0
    use_structure_break: bool = True
    structure_break_buffer: float = 0.005
    use_ma_exit: bool = True
    ma_fast: str = "ema20"
    ma_slow: str = "sma50"
    ma_exit_min_hold_days: int = 5
    use_time_stop: bool = True
    max_holding_days: int = 60
    time_stop_min_profit: float = 0.02
    use_stepped_trailing: bool = True
    trailing_steps: list[tuple[float, float]] = field(
        default_factory=lambda: [
            (6.0, 2.0),
            (4.0, 2.5),
            (2.0, 3.0),
            (0.0, 4.0),
        ]
    )
    use_partial_tp: bool = True
    partial_tp_rules: list[tuple[float, float, str]] = field(
        default_factory=lambda: [
            (3.0, 0.33, "move_to_breakeven"),
            (5.0, 0.33, "trail_2_atr"),
        ]
    )


class ExitManager:
    """按优先级检查结构、均线、时间和移动止损出场。"""

    def __init__(self, profile: Optional[ExitProfile] = None):
        self.profile = profile or ExitProfile()

    def check_exits(self, position: PositionState, bar: dict) -> Optional[ExitSignal]:
        """返回当前 K 线上优先级最高的出场信号。"""
        position.holding_days += 1
        position.highest_since_entry = max(
            position.highest_since_entry,
            float(bar.get("high", bar.get("close", position.entry_price))),
        )

        checks = [
            self._check_hard_stop,
            self._check_structure_break,
            self._check_partial_take_profit,
            self._check_ma_exit,
            self._check_time_stop,
            self._check_stepped_trailing,
        ]
        for check in checks:
            signal = check(position, bar)
            if signal is not None:
                return signal
        return None

    def _check_hard_stop(self, position: PositionState, bar: dict) -> Optional[ExitSignal]:
        stop_price = position.entry_price - self.profile.hard_stop_atr_mult * position.entry_atr
        if float(bar["close"]) <= stop_price:
            return ExitSignal(
                ExitReason.HARD_STOP,
                1.0,
                float(bar["close"]),
                f"hard stop {stop_price:.2f}",
            )
        return None

    def _check_structure_break(self, position: PositionState, bar: dict) -> Optional[ExitSignal]:
        if not self.profile.use_structure_break:
            return None
        buffer = position.entry_swing_low * self.profile.structure_break_buffer
        break_level = position.entry_swing_low - buffer
        if float(bar["close"]) < break_level:
            return ExitSignal(
                ExitReason.STRUCTURE_BREAK,
                1.0,
                float(bar["close"]),
                f"structure break below {break_level:.2f}",
            )
        return None

    def _check_partial_take_profit(self, position: PositionState, bar: dict) -> Optional[ExitSignal]:
        if not self.profile.use_partial_tp:
            return None
        atr = float(bar.get("atr", position.entry_atr))
        if atr <= 0:
            return None
        profit_atr = (float(bar["close"]) - position.entry_price) / atr
        for index, (target_atr, exit_pct, stop_action) in enumerate(self.profile.partial_tp_rules):
            if index in position.completed_partial_exits or profit_atr < target_atr:
                continue
            position.completed_partial_exits.add(index)
            self._adjust_stop_after_partial(position, stop_action, bar)
            return ExitSignal(
                ExitReason.PARTIAL_TAKE_PROFIT,
                exit_pct,
                float(bar["close"]),
                f"partial TP {exit_pct:.0%} at {profit_atr:.1f} ATR",
            )
        return None

    def _check_ma_exit(self, position: PositionState, bar: dict) -> Optional[ExitSignal]:
        if not self.profile.use_ma_exit or position.holding_days < self.profile.ma_exit_min_hold_days:
            return None
        fast = bar.get(self.profile.ma_fast)
        slow = bar.get(self.profile.ma_slow)
        if fast is None or slow is None:
            return None
        if float(bar["close"]) < float(fast) < float(slow):
            return ExitSignal(
                ExitReason.MA_EXIT,
                0.75,
                float(bar["close"]),
                f"close below {self.profile.ma_fast} and {self.profile.ma_fast} < {self.profile.ma_slow}",
            )
        return None

    def _check_time_stop(self, position: PositionState, bar: dict) -> Optional[ExitSignal]:
        if not self.profile.use_time_stop or position.holding_days <= self.profile.max_holding_days:
            return None
        pnl_pct = (float(bar["close"]) - position.entry_price) / position.entry_price
        if pnl_pct < self.profile.time_stop_min_profit:
            return ExitSignal(
                ExitReason.TIME_STOP,
                1.0,
                float(bar["close"]),
                f"time stop after {position.holding_days} days",
            )
        return None

    def _check_stepped_trailing(self, position: PositionState, bar: dict) -> Optional[ExitSignal]:
        if not self.profile.use_stepped_trailing:
            return None
        atr = float(bar.get("atr", position.entry_atr))
        if atr <= 0:
            return None
        profit_atr = (position.highest_since_entry - position.entry_price) / atr
        trailing_distance = self._trailing_distance(profit_atr, atr)
        trailing_stop = position.highest_since_entry - trailing_distance
        if float(bar["close"]) < trailing_stop:
            return ExitSignal(
                ExitReason.TRAILING_STOP,
                1.0,
                float(bar["close"]),
                f"trailing stop {trailing_stop:.2f}",
            )
        return None

    def _trailing_distance(self, profit_atr: float, atr: float) -> float:
        for threshold, multiplier in self.profile.trailing_steps:
            if profit_atr >= threshold:
                return multiplier * atr
        return self.profile.trailing_steps[-1][1] * atr

    def _adjust_stop_after_partial(self, position: PositionState, action: str, bar: dict) -> None:
        atr = float(bar.get("atr", position.entry_atr))
        if action == "move_to_breakeven":
            position.stop_price = position.entry_price
        elif action.startswith("trail_"):
            multiplier = float(action.split("_", 1)[1])
            position.stop_price = float(bar["close"]) - multiplier * atr


def create_btc_exit_profile() -> ExitProfile:
    """BTC 出场配置。"""
    return ExitProfile()


def create_eth_exit_profile() -> ExitProfile:
    """ETH 出场配置，移动止损更宽。"""
    return ExitProfile(
        structure_break_buffer=0.008,
        trailing_steps=[
            (6.0, 2.5),
            (4.0, 3.0),
            (2.0, 3.5),
            (0.0, 4.5),
        ],
    )
