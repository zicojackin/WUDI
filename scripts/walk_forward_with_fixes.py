"""滚动样本外对比：基线 vs 修复后策略。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest_with_fixes import run_backtest_with_fixes


def rolling_windows(
    frame: pd.DataFrame,
    start: str,
    end: str,
    test_days: int,
    step_days: int,
) -> list[tuple[str, str]]:
    dates = pd.to_datetime(frame["date"])
    current = pd.Timestamp(start)
    final = pd.Timestamp(end)
    windows = []
    while current <= final:
        window_end = min(current + pd.Timedelta(days=test_days - 1), final)
        if dates.min() > window_end:
            break
        windows.append((str(current.date()), str(window_end.date())))
        current += pd.Timedelta(days=step_days)
    return windows


def summarize(results: list[dict]) -> dict:
    returns = [result["metrics"].total_return for result in results]
    sharpes = [result["metrics"].sharpe_ratio for result in results]
    positive = sum(value > 0 for value in returns)
    compounded = 1.0
    for value in returns:
        compounded *= 1 + value
    return {
        "folds": len(results),
        "positive_folds": positive,
        "consistency": positive / len(results) if results else 0.0,
        "avg_return": sum(returns) / len(results) if results else 0.0,
        "compounded_return": compounded - 1.0,
        "avg_sharpe": sum(sharpes) / len(sharpes) if sharpes else 0.0,
    }


def compare(
    label: str,
    baseline: dict,
    fixed: dict,
) -> None:
    print(f"\n{label} Walk-forward 对比")
    print(f"  {'指标':<24} {'基线':<14} {'修复后':<14}")
    print(f"  {'-' * 52}")
    for name in ["folds", "positive_folds", "consistency", "avg_return", "compounded_return", "avg_sharpe"]:
        base_value = baseline[name]
        fixed_value = fixed[name]
        if name in {"consistency", "avg_return", "compounded_return"}:
            print(f"  {name:<24} {base_value:<14.2%} {fixed_value:<14.2%}")
        elif name in {"avg_sharpe"}:
            print(f"  {name:<24} {base_value:<14.3f} {fixed_value:<14.3f}")
        else:
            print(f"  {name:<24} {base_value:<14d} {fixed_value:<14d}")


def main() -> None:
    parser = argparse.ArgumentParser(description="修复前后滚动样本外对比")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-09-04")
    parser.add_argument("--test-days", type=int, default=90)
    parser.add_argument("--step-days", type=int, default=90)
    parser.add_argument("--use-eth-exit-v2", action="store_true")
    args = parser.parse_args()

    data_dir = Path("data")
    for symbol in args.symbols:
        symbol = symbol.upper()
        base_asset = symbol[:3]
        data_file = data_dir / f"{base_asset}_1d.csv"
        if not data_file.exists():
            print(f"缺少数据文件: {data_file}")
            continue

        frame = pd.read_csv(data_file)
        windows = rolling_windows(frame, args.start, args.end, args.test_days, args.step_days)
        baseline_results = []
        fixed_results = []

        for start, end in windows:
            try:
                baseline_results.append(
                    run_backtest_with_fixes(
                        frame,
                        start,
                        end,
                        symbol,
                        use_exit_optimizer=False,
                        use_eth_fix=False,
                        use_trend_base=False,
                    )
                )
            except ValueError:
                continue

            try:
                fixed_results.append(
                    run_backtest_with_fixes(
                        frame,
                        start,
                        end,
                        symbol,
                        use_exit_optimizer=True,
                        use_eth_fix=symbol == "ETHUSDT",
                        use_eth_exit_v2=args.use_eth_exit_v2 and symbol == "ETHUSDT",
                        use_trend_base=True,
                    )
                )
            except ValueError:
                continue

        baseline_summary = summarize(baseline_results)
        fixed_summary = summarize(fixed_results)
        compare(symbol, baseline_summary, fixed_summary)


if __name__ == "__main__":
    main()
