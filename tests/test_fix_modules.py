from crypto_trading_agents.eth_fix import ETHFixConfig, ETHFixManager
from crypto_trading_agents.exit_optimizer import ExitOptimizer
from crypto_trading_agents.trend_base_simple import TrendBaseSimple


def test_exit_optimizer_tolerates_pullback() -> None:
    optimizer = ExitOptimizer()
    optimizer.reset()
    position = {
        "entry_price": 100.0,
        "entry_atr": 2.0,
        "highest_since_entry": 106.0,
        "holding_days": 10,
        "entry_swing_low": 92.0,
    }
    should_exit, _, _ = optimizer.should_exit(
        position,
        {"close": 103.0, "atr": 2.0, "ema20": 101.0, "sma50": 99.0},
    )
    assert not should_exit


def test_trend_base_simple_opens_and_closes() -> None:
    base = TrendBaseSimple()
    assert base.on_bar(
        {"date": "2026-01-01", "close": 100.0, "high": 101.0, "sma200": 90.0, "atr": 2.0},
        {"ema20": 105.0, "ema50": 100.0},
    ) == "open"
    assert base.on_bar(
        {"date": "2026-01-02", "close": 70.0, "high": 75.0, "sma200": 90.0, "atr": 2.0},
        {"ema20": 105.0, "ema50": 100.0},
    ) == "close"


def test_eth_fix_blocks_accumulation() -> None:
    manager = ETHFixManager(ETHFixConfig())
    allowed, _, reason = manager.should_enter(
        stage="accumulation",
        pattern="capitulation_reversal",
        setup_score=90.0,
        pattern_quality=95.0,
        relative_strength=95.0,
        volume_ratio=2.0,
    )
    assert not allowed
    assert "forbidden" in reason
