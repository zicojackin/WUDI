"""分年度、Alpha/Beta 与市场阶段归因。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest_with_fixes import run_backtest_with_fixes


def yearly_attribution(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    symbol: str,
) -> None:
    print(f"\n{'=' * 70}")
    print(f"{symbol} 分年度归因")
    print(f"{'=' * 70}")
    print(f"  {'年份':<6} {'策略':<12} {'基准':<12} {'超额':<12} {'暴露':<8} {'Sharpe':<8}")

    for year in sorted(strategy_returns.index.year.unique()):
        mask = strategy_returns.index.year == year
        strategy_year = strategy_returns[mask]
        benchmark_year = benchmark_returns[mask]
        strategy_return = (1 + strategy_year).prod() - 1
        benchmark_return = (1 + benchmark_year).prod() - 1
        exposure = (strategy_year != 0).mean()
        sharpe = (
            np.sqrt(365) * strategy_year.mean() / strategy_year.std()
            if strategy_year.std() > 0
            else 0.0
        )
        print(
            f"  {year:<6} {strategy_return:<+12.2%} {benchmark_return:<+12.2%} "
            f"{strategy_return - benchmark_return:<+12.2%} {exposure:<8.1%} {sharpe:<8.3f}"
        )


def alpha_beta_decomposition(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    base_returns: pd.Series,
    signal_returns: pd.Series,
    symbol: str,
) -> dict:
    total_return = (1 + strategy_returns).prod() - 1
    base_return = (1 + base_returns).prod() - 1
    signal_return = (1 + signal_returns).prod() - 1
    benchmark_return = (1 + benchmark_returns).prod() - 1
    base_exposure = (base_returns != 0).mean()
    base_capture = base_return / benchmark_return if benchmark_return else 0.0
    info_ratio = (
        np.sqrt(365) * signal_returns.mean() / signal_returns.std()
        if signal_returns.std() > 0
        else 0.0
    )

    print(f"\n{'=' * 70}")
    print(f"{symbol} Alpha / Beta 分离")
    print(f"{'=' * 70}")
    print(f"  策略总收益:      {total_return:+.2%}")
    print(f"  底仓 Beta 收益:  {base_return:+.2%}")
    print(f"  信号 Alpha 收益: {signal_return:+.2%}")
    print(f"  买入持有:        {benchmark_return:+.2%}")
    print(f"  底仓暴露:        {base_exposure:.1%}")
    print(f"  底仓收益捕获率:  {base_capture:.1%}")
    print(f"  信号层信息比率:  {info_ratio:.3f}")

    return {
        "total_return": total_return,
        "base_return": base_return,
        "signal_return": signal_return,
        "benchmark_return": benchmark_return,
        "base_capture_ratio": base_capture,
        "signal_information_ratio": info_ratio,
    }


def regime_analysis(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    symbol: str,
) -> None:
    benchmark_60d = benchmark_returns.rolling(60).apply(lambda x: (1 + x).prod() - 1)
    regimes = pd.Series("range", index=strategy_returns.index)
    regimes[benchmark_60d > 0.30] = "bull"
    regimes[benchmark_60d < -0.30] = "bear"

    print(f"\n{'=' * 70}")
    print(f"{symbol} 分市场阶段表现")
    print(f"{'=' * 70}")
    for regime in ["bull", "bear", "range"]:
        mask = regimes == regime
        if not mask.any():
            continue
        strategy_return = (1 + strategy_returns[mask]).prod() - 1
        benchmark_return = (1 + benchmark_returns[mask]).prod() - 1
        exposure = (strategy_returns[mask] != 0).mean()
        print(
            f"  {regime.upper()} ({int(mask.sum())} 天): "
            f"策略 {strategy_return:+.2%}, 基准 {benchmark_return:+.2%}, 暴露 {exposure:.1%}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="修复后策略归因分析")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-09-04")
    parser.add_argument("--data-file")
    parser.add_argument("--use-eth-exit-v2", action="store_true")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    data_file = Path(args.data_file or f"data/{symbol[:3]}_1d.csv")
    frame = pd.read_csv(data_file)
    output = run_backtest_with_fixes(
        frame,
        args.start,
        args.end,
        symbol,
        use_exit_optimizer=True,
        use_eth_fix=symbol == "ETHUSDT",
        use_eth_exit_v2=args.use_eth_exit_v2 and symbol == "ETHUSDT",
        use_trend_base=True,
    )

    benchmark_returns = frame.set_index(pd.to_datetime(frame["date"]))["close"].pct_change().fillna(0.0)
    yearly_attribution(output["combined_returns"], benchmark_returns, symbol)
    attribution = alpha_beta_decomposition(
        output["combined_returns"],
        benchmark_returns,
        output["base_returns"],
        output["signal_returns"],
        symbol,
    )
    regime_analysis(output["combined_returns"], benchmark_returns, symbol)
    print("\nJSON:")
    print(attribution)


if __name__ == "__main__":
    main()
