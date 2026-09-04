import pandas as pd

from crypto_trading_agents.entry_manager import EntryManager, EntryTier
from crypto_trading_agents.exit_manager import ExitManager, ExitProfile, PositionState
from crypto_trading_agents.metrics import compute_risk_metrics
from scripts.validate_data import validate_ohlcv_frame


def test_compute_risk_metrics_counts_consecutive_losses() -> None:
    returns = pd.Series([0.01, -0.01, -0.02, 0.005, -0.01, 0.02])
    metrics = compute_risk_metrics(returns, trade_pnl_list=[100, -50, -30, 80])
    assert metrics.max_consecutive_losses == 2
    assert metrics.total_trades == 4
    assert metrics.win_rate == 0.5


def test_entry_manager_assigns_tier_a() -> None:
    manager = EntryManager()
    tier, position_pct, details = manager.evaluate_entry(
        {
            "cycle_phase": "markup",
            "setup_score": 80,
            "pattern_quality": 80,
            "structure_score": 80,
            "relative_strength_score": 80,
            "volume": 100,
            "volume_ma": 50,
        },
        {"close": 110, "ema20": 100, "ema50": 90},
    )
    assert tier == EntryTier.A
    assert position_pct == 1.0
    assert details["composite_score"] > 0


def test_exit_manager_triggers_hard_stop() -> None:
    manager = ExitManager(ExitProfile(use_partial_tp=False))
    position = PositionState(
        entry_price=100.0,
        entry_date=pd.Timestamp("2026-01-01"),
        entry_swing_low=90.0,
        entry_atr=2.0,
        highest_since_entry=100.0,
        current_size=1.0,
        initial_size=1.0,
    )
    signal = manager.check_exits(
        position,
        {
            "close": 94.0,
            "high": 95.0,
            "low": 93.0,
            "atr": 2.0,
            "ema20": 99.0,
            "sma50": 98.0,
        },
    )
    assert signal is not None
    assert signal.reason.value == "hard_stop"


def test_validate_ohlcv_frame_detects_invalid_range() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5),
            "open": [10, 10, 10, 10, 10],
            "high": [11, 11, 11, 11, 9],
            "low": [9, 9, 9, 9, 12],
            "close": [10, 10, 10, 10, 10],
            "volume": [10, 10, 10, 10, 10],
        }
    )
    result = validate_ohlcv_frame(frame, "TEST")
    assert not result["passed"]
    assert any("high/low" in issue for issue in result["issues"])
