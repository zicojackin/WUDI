"""核心参数扰动测试，用于判断是否过拟合。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_trading_agents.cycle import CycleConfig, backtest_cycle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest_cycle_full import fetch_klines


def load_data(args: argparse.Namespace) -> pd.DataFrame:
    if args.data_file:
        return pd.read_csv(args.data_file)
    return fetch_klines(args.symbol, "1d", args.start, args.end)


def sharpe_from_result(result) -> float:
    return float(result.risk_metrics.sharpe_ratio)


def check_parameter_stability(frame: pd.DataFrame, args: argparse.Namespace) -> None:
    parameter_sets = {
        "min_setup_score": [40, 50, 60, 70, 80],
        "min_pattern_quality": [25, 35, 40, 50, 60],
        "stop_atr_multiple": [1.5, 2.0, 2.5, 3.0],
        "trail_atr_multiple": [2.0, 3.0, 4.0, 5.0],
    }

    print(f"\n{'=' * 64}")
    print("参数稳定性检查")
    print(f"{'=' * 64}")

    for parameter_name, values in parameter_sets.items():
        rows = []
        for value in values:
            config = replace(
                CycleConfig(),
                risk_per_trade=args.risk_per_trade,
                **{parameter_name: value},
            )
            if parameter_name in {"stop_atr_multiple", "trail_atr_multiple"}:
                config.use_asset_profile = False
            result = backtest_cycle(
                frame,
                args.start,
                args.end,
                config,
                symbol=args.symbol.upper(),
            )
            rows.append(
                {
                    "value": value,
                    "sharpe": result.risk_metrics.sharpe_ratio,
                    "return": result.strategy_return_pct,
                    "max_drawdown": result.max_drawdown_pct,
                    "trades": result.trade_count,
                }
            )

        frame_results = pd.DataFrame(rows)
        sharpe_std = float(frame_results["sharpe"].std())
        sharpe_mean = float(frame_results["sharpe"].mean())
        coefficient = sharpe_std / (abs(sharpe_mean) + 1e-12)
        status = "stable" if coefficient < 0.3 else ("moderate" if coefficient < 0.6 else "sensitive")
        print(f"\n{parameter_name}: {status} (CV={coefficient:.2f})")
        for _, row in frame_results.iterrows():
            print(
                f"  {parameter_name}={row['value']}: "
                f"Sharpe={row['sharpe']:.3f}, "
                f"Return={row['return']:+.2f}%, "
                f"MaxDD={row['max_drawdown']:.2f}%, "
                f"Trades={int(row['trades'])}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="核心参数扰动测试")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-09-04")
    parser.add_argument("--data-file")
    parser.add_argument("--risk-per-trade", type=float, default=0.03)
    args = parser.parse_args()

    frame = load_data(args)
    check_parameter_stability(frame, args)


if __name__ == "__main__":
    main()
