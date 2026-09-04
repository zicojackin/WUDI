import pandas as pd

from crypto_trading_agents.cycle import backtest_cycle, prepare_cycle_frame


def test_prepare_cycle_frame_adds_stage_columns() -> None:
    dates = pd.date_range("2026-01-01", periods=260, freq="D")
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 10.0,
        }
    )
    result = prepare_cycle_frame(frame)
    assert "stage" in result.columns
    assert "weekly_trend" in result.columns
    assert "cycle_state" in result.columns
    assert "swing_trend" in result.columns
    assert "pattern_quality" in result.columns
    assert "setup_score" in result.columns
    assert "entry_ready" in result.columns
    assert "relative_strength_score" in result.columns
    assert "quality_tightness" in result.columns
    assert "quality_volume" in result.columns
    assert "quality_trend" in result.columns
    assert "quality_cycle" in result.columns
    assert "quality_swing" in result.columns
    assert "quality_trigger" in result.columns
    assert result["stage"].notna().all()
    assert result["cycle_state"].isin(
        ["unknown", "accumulation", "recovery", "markup", "distribution", "markdown"]
    ).all()
    assert result["pattern_quality"].between(0, 100).all()
    assert result["setup_score"].between(0, 100).all()
    assert result["relative_strength_score"].between(0, 100).all()


def test_backtest_cycle_returns_metrics_on_flat_data() -> None:
    dates = pd.date_range("2026-01-01", periods=260, freq="D")
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 10.0,
        }
    )
    result = backtest_cycle(frame, "2026-01-01", "2026-12-31")
    assert result.trade_count == 0
    assert len(result.equity_curve) == 260
    assert result.risk_metrics.total_trades == 0
    assert result.risk_metrics.max_drawdown == 0
