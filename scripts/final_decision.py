"""Run the final BTC/ETH review and print a go/no-go recommendation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crypto_trading_agents.cycle import (
    CycleConfig,
    walk_forward_cycle,
)
from crypto_trading_agents.monte_carlo import MonteCarloConfig, MonteCarloSimulator
from scripts.backtest_with_fixes import run_backtest_with_fixes
from scripts.validate_data import validate_ohlcv_frame


def load_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing data file: {path}")
    return pd.read_csv(path)


def signal_information_ratio(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    if len(clean) < 2 or clean.std(ddof=0) <= 1e-12:
        return 0.0
    return float(np.sqrt(365.0) * clean.mean() / clean.std(ddof=0))


def build_checklist(
    btc_data: dict,
    eth_data: dict,
    walk_forward_folds: list[dict],
) -> list[tuple[str, bool, str]]:
    btc_metrics = btc_data["metrics"]
    eth_metrics = eth_data["metrics"]
    trade_pnl = btc_data["trade_pnl"]
    wf_positive = sum(float(row["test_return_pct"]) > 0 for row in walk_forward_folds)
    wf_ratio = wf_positive / len(walk_forward_folds) if walk_forward_folds else 0.0

    return [
        (
            "BTC trade expectation > 0",
            bool(trade_pnl and np.mean(trade_pnl) > 0),
            f"mean_trade_pnl={np.mean(trade_pnl) if trade_pnl else 0.0:.5f}",
        ),
        (
            "BTC combined Sharpe > 1.0",
            btc_metrics.sharpe_ratio > 1.0,
            f"sharpe={btc_metrics.sharpe_ratio:.3f}",
        ),
        (
            "BTC signal IR > 0.5",
            btc_data["signal_ir"] > 0.5,
            f"signal_ir={btc_data['signal_ir']:.3f}",
        ),
        (
            "BTC walk-forward positive > 25%",
            wf_ratio > 0.25,
            f"{wf_positive}/{len(walk_forward_folds)} ({wf_ratio:.1%})",
        ),
        (
            "BTC combined max drawdown > -15%",
            btc_metrics.max_drawdown > -0.15,
            f"max_drawdown={btc_metrics.max_drawdown:.2%}",
        ),
        (
            "ETH base-layer return > 0",
            eth_metrics.total_return > 0,
            f"total_return={eth_metrics.total_return:.2%}",
        ),
        (
            "ETH signal layer disabled",
            not eth_data["strategy"].config.signal_layer_enabled,
            "ordinary entry signals ignored",
        ),
        (
            "ETH max drawdown > -25%",
            eth_metrics.max_drawdown > -0.25,
            f"max_drawdown={eth_metrics.max_drawdown:.2%}",
        ),
        (
            "ETH exception gate >= 85/85",
            eth_data["strategy"].config.exception_min_setup_score >= 85.0
            and eth_data["strategy"].config.exception_min_pattern_quality >= 85.0,
            "strict exception rule configured",
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Final strategy go/no-go review")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-09-04")
    parser.add_argument("--train-days", type=int, default=365)
    parser.add_argument("--test-days", type=int, default=90)
    parser.add_argument("--skip-walk-forward", action="store_true")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    btc_frame = load_frame(data_dir / "BTC_1d.csv")
    eth_frame = load_frame(data_dir / "ETH_1d.csv")

    btc_validation = validate_ohlcv_frame(btc_frame, "BTCUSDT")
    eth_validation = validate_ohlcv_frame(eth_frame, "ETHUSDT")
    if not btc_validation["passed"] or not eth_validation["passed"]:
        raise ValueError(
            f"data validation failed: BTC={btc_validation['issues']}, "
            f"ETH={eth_validation['issues']}"
        )

    btc = run_backtest_with_fixes(
        btc_frame,
        args.start,
        args.end,
        "BTCUSDT",
        use_trend_base=True,
        use_btc_exit_final=True,
        base_position_pct=0.15,
    )
    eth = run_backtest_with_fixes(
        eth_frame,
        args.start,
        args.end,
        "ETHUSDT",
        use_eth_strategy_v3=True,
    )

    config = CycleConfig(
        execution_mode="daily",
        risk_per_trade=0.03,
        use_btc_exit_final=True,
    )
    if args.skip_walk_forward:
        folds = []
    else:
        folds = walk_forward_cycle(
            btc_frame,
            args.start,
            args.end,
            config=config,
            train_days=args.train_days,
            test_days=args.test_days,
            setup_score_candidates=(60.0,),
            symbol="BTCUSDT",
        )

    btc_trades = btc["result"].trades
    btc_pnl = [trade.notional * trade.return_pct / 100.0 for trade in btc_trades]
    btc_data = {
        "metrics": btc["metrics"],
        "signal_ir": signal_information_ratio(btc["signal_returns"]),
        "trade_pnl": btc_pnl,
    }

    print("\nBTC final strategy")
    print(f"  combined_return={btc['metrics'].total_return:.2%}")
    print(f"  combined_sharpe={btc['metrics'].sharpe_ratio:.3f}")
    print(f"  combined_max_drawdown={btc['metrics'].max_drawdown:.2%}")
    print(f"  combined_exposure={btc['metrics'].exposure_pct:.2%}")
    print(f"  signal_trades={len(btc_trades)}")
    print(f"  signal_ir={btc_data['signal_ir']:.3f}")

    eth_metrics = eth["metrics"]
    print("\nETH V3 strategy")
    print(f"  total_return={eth_metrics.total_return:.2%}")
    print(f"  annual_return={eth_metrics.annual_return:.2%}")
    print(f"  sharpe={eth_metrics.sharpe_ratio:.3f}")
    print(f"  max_drawdown={eth_metrics.max_drawdown:.2%}")
    print(f"  exposure={eth_metrics.exposure_pct:.2%}")
    print(f"  buy_and_hold={eth['buy_and_hold_return']:.2%}")
    print(f"  base_actions={len(eth['base_actions'])}")
    print(f"  exception_adds={len(eth['exception_actions'])}")

    if not args.skip_walk_forward:
        wf_positive = sum(float(row["test_return_pct"]) > 0 for row in folds)
        print("\nBTC walk-forward")
        print(f"  folds={len(folds)}")
        print(f"  positive={wf_positive}")
        print(f"  consistency={wf_positive / len(folds) if folds else 0:.1%}")

    if len(btc_pnl) >= 3:
        simulator = MonteCarloSimulator(
            MonteCarloConfig(n_simulations=10000, initial_capital=10000.0)
        )
        print("\nBTC Monte Carlo")
        print(simulator.bootstrap_simulation(btc_pnl).summary())
    else:
        print("\nBTC Monte Carlo skipped: fewer than 3 closed trades")

    checks = build_checklist(btc_data, eth, folds)
    print("\nGo/No-Go checklist")
    passed_count = 0
    for name, passed, detail in checks:
        passed_count += int(passed)
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    print(f"  passed={passed_count}/{len(checks)}")

    btc_checks = checks[:5]
    eth_checks = checks[5:]
    if all(passed for _, passed, _ in btc_checks) and all(
        passed for _, passed, _ in eth_checks
    ):
        recommendation = "GO: proceed to 60-day paper trading."
    elif all(passed for _, passed, _ in btc_checks):
        recommendation = "CONDITIONAL GO: paper trade BTC only; keep ETH disabled."
    else:
        recommendation = "NO-GO: do not start paper trading yet."

    print(f"\nRecommendation: {recommendation}")
    print("\nLimitations")
    print("  - Trend timing underperforms buy-and-hold in persistent bull markets.")
    print("  - Walk-forward consistency may remain low despite positive long-run PnL.")
    print("  - ETH entry signals remain unvalidated; only the base layer is used.")
    print("  - Sample size is still limited; paper trade before any live capital.")


if __name__ == "__main__":
    main()
