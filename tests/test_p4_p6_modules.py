import numpy as np
import pandas as pd

from crypto_trading_agents.adaptive_exit import AdaptiveExitManager, MarketRegime
from crypto_trading_agents.monte_carlo import MonteCarloConfig, MonteCarloSimulator
from crypto_trading_agents.multi_timeframe import MultiTimeframeEntry
from crypto_trading_agents.portfolio_risk import PortfolioRiskManager
from crypto_trading_agents.sentiment_filter import SentimentFilter
from crypto_trading_agents.trend_base import TrendBaseManager


def test_multi_timeframe_entry_detects_pullback() -> None:
    engine = MultiTimeframeEntry()
    daily = {
        "date": pd.Timestamp("2026-01-01"),
        "close": 100.0,
        "low": 95.0,
        "setup_score": 65.0,
        "pattern_quality": 70.0,
        "cycle_phase": "reversal_extension",
        "atr": 3.0,
    }
    assert engine.on_daily_bar(daily, 65.0) is not None
    trigger = engine.on_4h_bar(
        {
            "timestamp": pd.Timestamp("2026-01-02"),
            "open": 98.0,
            "high": 99.0,
            "low": 96.0,
            "close": 98.5,
            "volume": 100,
            "volume_ma": 80,
            "atr": 1.0,
            "ema20": 97.0,
        }
    )
    assert trigger is not None
    assert trigger.trigger_type == "pullback_bounce"


def test_adaptive_exit_detects_hard_stop() -> None:
    manager = AdaptiveExitManager()
    signal = manager.check_exit(
        {"entry_price": 100.0, "entry_atr": 2.0, "highest_since_entry": 100.0, "holding_days": 3},
        {"close": 90.0, "atr": 2.0},
        MarketRegime.LOW_VOL_TREND,
    )
    assert signal is not None
    assert "adaptive_hard_stop" in signal["reason"]


def test_monte_carlo_simulation_runs() -> None:
    simulator = MonteCarloSimulator(
        MonteCarloConfig(n_simulations=100, initial_capital=10000.0, random_seed=7)
    )
    result = simulator.bootstrap_simulation([0.10, -0.05, 0.08, -0.03, 0.12], n_trades_per_sim=20)
    assert len(result.final_equities) == 100
    assert 0 <= result.stats["prob_ruin"] <= 1


def test_sentiment_filter_multiplies_position() -> None:
    manager = SentimentFilter()
    manager.load_series(
        pd.Series([80], index=[pd.Timestamp("2026-01-01")])
    )
    assert manager.get_position_multiplier(pd.Timestamp("2026-01-02")) < 1.0
    assert manager.get_signal_adjustment(pd.Timestamp("2026-01-02")) < 0


def test_portfolio_risk_manager_reduces_risk_on_drawdown() -> None:
    manager = PortfolioRiskManager()
    manager.update(100.0, pd.Timestamp("2026-01-01"))
    level, multiplier = manager.update(93.0, pd.Timestamp("2026-01-02"), -0.07)
    assert level.value in {"cautious", "defensive"}
    assert multiplier < 1.0


def test_trend_base_manager_opens_base_position() -> None:
    manager = TrendBaseManager()
    action = manager.on_daily_bar(
        {
            "close": 100.0,
            "sma200": 90.0,
            "atr": 2.0,
        },
        {"close": 105.0, "ema20": 100.0, "ema50": 95.0},
        "markup",
    )
    assert action is not None
    assert action["type"] == "open_base"
