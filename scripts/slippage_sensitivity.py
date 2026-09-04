"""Run slippage sensitivity for BTC and ETH across 0.05% / 0.1% / 0.2%."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest_with_fixes import run_backtest_with_fixes


def main() -> None:
    parser = argparse.ArgumentParser(description="Slippage sensitivity analysis")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-09-04")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    slippage_levels = [0.0005, 0.001, 0.002]
    labels = ["0.05%", "0.10%", "0.20%"]

    for symbol, use_eth_v3 in [("BTCUSDT", False), ("ETHUSDT", True)]:
        asset = symbol[:3]
        data_file = data_dir / f"{asset}_1d.csv"
        if not data_file.exists():
            print(f"  skip: {data_file} not found")
            continue

        frame = pd.read_csv(data_file)
        use_trend_base = not use_eth_v3
        use_btc_exit_final = symbol == "BTCUSDT"

        print(f"\n{'=' * 60}")
        print(f"  {symbol} slippage sensitivity")
        print(f"{'=' * 60}")
        print(f"  {'Slippage':<12} {'Return':<14} {'Sharpe':<10} {'MaxDD':<12} {'Exposure':<10}")
        print(f"  {'-' * 56}")

        for slippage, label in zip(slippage_levels, labels):
            try:
                output = run_backtest_with_fixes(
                    frame,
                    args.start,
                    args.end,
                    symbol,
                    use_trend_base=use_trend_base,
                    use_btc_exit_final=use_btc_exit_final,
                    use_eth_strategy_v3=use_eth_v3,
                    slippage_rate=slippage,
                )
                metrics = output["metrics"]
                print(
                    f"  {label:<12} {metrics.total_return:<+14.2%} "
                    f"{metrics.sharpe_ratio:<10.3f} {metrics.max_drawdown:<+12.2%} "
                    f"{metrics.exposure_pct:<10.2%}"
                )
            except Exception as exc:
                print(f"  {label:<12} ERROR: {exc}")

    print(f"\n  baseline cost: fee=0.1% per side, slippage as shown, funding=10% annual")


if __name__ == "__main__":
    main()
