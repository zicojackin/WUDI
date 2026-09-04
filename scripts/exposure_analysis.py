"""暴露成本分析：空仓期间错过了多少基准收益。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from crypto_trading_agents.cycle import CycleConfig, backtest_cycle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest_cycle_full import fetch_klines


def load_price(args: argparse.Namespace) -> pd.DataFrame:
    if args.data_file:
        return pd.read_csv(args.data_file)
    return fetch_klines(args.symbol, "1d", args.start, args.end)


def analyze_exposure(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    position_flags: pd.Series,
) -> dict:
    strategy_returns = strategy_returns.copy()
    benchmark_returns = benchmark_returns.copy()
    position_flags = position_flags.copy()
    common_index = strategy_returns.index.intersection(benchmark_returns.index)
    strategy_returns = strategy_returns.loc[common_index]
    benchmark_returns = benchmark_returns.loc[common_index]
    position_flags = position_flags.loc[common_index]

    holding = position_flags.astype(bool)
    empty = ~holding
    missed_return = benchmark_returns[empty]
    holding_strategy_return = (1 + strategy_returns[holding]).prod() - 1
    holding_benchmark_return = (1 + benchmark_returns[holding]).prod() - 1
    missed_cumulative_return = (1 + missed_return).prod() - 1

    print(f"\n{'=' * 64}")
    print("暴露成本分析")
    print(f"{'=' * 64}")
    print(f"总天数: {len(common_index)}")
    print(f"持仓天数: {int(holding.sum())} ({holding.mean():.1%})")
    print(f"空仓天数: {int(empty.sum())} ({empty.mean():.1%})")
    print(f"空仓期间基准收益: {missed_cumulative_return:+.2%}")
    print(f"持仓期间策略收益: {holding_strategy_return:+.2%}")
    print(f"持仓期间基准收益: {holding_benchmark_return:+.2%}")
    print(f"持仓期间超额: {holding_strategy_return - holding_benchmark_return:+.2%}")
    print(
        f"空仓期间方向: "
        f"{int((missed_return > 0).sum())} 天上涨 / "
        f"{int((missed_return < 0).sum())} 天下跌"
    )

    return {
        "missed_return": missed_cumulative_return,
        "holding_strategy_return": holding_strategy_return,
        "holding_benchmark_return": holding_benchmark_return,
        "exposure_pct": float(holding.mean()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="分析空仓期间错过的基准收益")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-09-04")
    parser.add_argument("--data-file")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    frame = load_price(args)
    config = CycleConfig()
    result = backtest_cycle(frame, args.start, args.end, config, symbol=symbol)

    strategy_returns = pd.Series(
        [row["return"] for row in result.daily_returns],
        index=pd.to_datetime([row["date"] for row in result.daily_returns]),
    )
    position_flags = pd.Series(
        [row["in_position"] for row in result.position_flags],
        index=pd.to_datetime([row["date"] for row in result.position_flags]),
    )
    benchmark_returns = frame.set_index(pd.to_datetime(frame["date"]))["close"].pct_change()
    benchmark_returns.index = benchmark_returns.index.date
    strategy_returns.index = strategy_returns.index.date
    position_flags.index = position_flags.index.date

    analyze_exposure(strategy_returns, benchmark_returns, position_flags)


if __name__ == "__main__":
    main()
