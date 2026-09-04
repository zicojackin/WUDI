"""展示优化模块如何与现有 Cycle 回测集成的示例脚本。"""

from __future__ import annotations

import argparse
from collections import Counter
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crypto_trading_agents.cycle import (
    CycleConfig,
    backtest_cycle,
    prepare_cycle_frame,
)
from crypto_trading_agents.entry_manager import (
    EntryManager,
    EntryTier,
    create_btc_entry_profile,
    create_eth_entry_profile,
)
from crypto_trading_agents.exit_manager import (
    ExitManager,
    create_btc_exit_profile,
    create_eth_exit_profile,
)
from scripts.validate_data import load_csv, validate_ohlcv_frame
from scripts.backtest_cycle_full import fetch_klines


def load_data(args: argparse.Namespace) -> pd.DataFrame:
    if args.data_file:
        frame = load_csv(args.data_file).reset_index().rename(columns={"index": "date"})
        if isinstance(frame["date"].dtype, pd.DatetimeTZDtype):
            frame["date"] = frame["date"].dt.tz_localize(None)
        return frame

    return fetch_klines(args.symbol, "1d", args.start, args.end)


def main() -> None:
    parser = argparse.ArgumentParser(description="运行带数据校验和风险指标的 Cycle 回测")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--benchmark-symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2024-09-04")
    parser.add_argument("--end", default="2026-09-04")
    parser.add_argument("--data-file")
    parser.add_argument("--risk-per-trade", type=float, default=0.03)
    parser.add_argument("--min-setup-score", type=float, default=60.0)
    args = parser.parse_args()

    symbol = args.symbol.upper()
    benchmark_symbol = (
        "ETHUSDT" if symbol == "BTCUSDT" else args.benchmark_symbol.upper()
    )
    frame = load_data(args)
    benchmark_frame = fetch_klines(benchmark_symbol, "1d", args.start, args.end)
    intraday_frame = fetch_klines(args.symbol, "4h", args.start, args.end)
    validation = validate_ohlcv_frame(frame, symbol)
    if not validation["passed"]:
        raise SystemExit(f"数据校验失败: {validation['issues']}")

    config = CycleConfig(
        risk_per_trade=args.risk_per_trade,
        min_setup_score=args.min_setup_score,
    )
    result = backtest_cycle(
        frame,
        args.start,
        args.end,
        config,
        intraday_frame=intraday_frame,
        benchmark_frame=benchmark_frame,
        symbol=symbol,
    )

    print("数据校验:")
    print(f"  rows={validation['stats']['total_rows']}")
    print(f"  range={validation['stats']['start']} ~ {validation['stats']['end']}")
    if validation["warnings"]:
        print("  warnings:")
        for warning in validation["warnings"]:
            print(f"    - {warning}")

    print("\n风险指标:")
    print(result.risk_metrics.summary())

    prepared = prepare_cycle_frame(
        frame,
        config,
        intraday_frame=intraday_frame,
        benchmark_frame=benchmark_frame,
        symbol=symbol,
    )
    entry_manager = EntryManager(
        create_btc_entry_profile() if symbol == "BTCUSDT" else create_eth_entry_profile()
    )
    tiers: Counter[str] = Counter()
    for _, row in prepared[prepared["entry_ready"]].iterrows():
        tier, _, _ = entry_manager.evaluate_entry(row.to_dict())
        if tier != EntryTier.SKIP:
            tiers[tier.value] += 1

    exit_manager = ExitManager(
        create_btc_exit_profile() if symbol == "BTCUSDT" else create_eth_exit_profile()
    )

    print("\n入场分层:")
    for tier in ["A", "B", "C"]:
        print(f"  {tier}: {tiers.get(tier, 0)}")
    print("\n出场配置:")
    print(f"  hard_stop={exit_manager.profile.hard_stop_atr_mult} x ATR")
    print(f"  max_holding_days={exit_manager.profile.max_holding_days}")
    print(f"  trades={result.trade_count}")
    print(f"  return={result.strategy_return_pct:.2f}%")
    print(f"  max_drawdown={result.max_drawdown_pct:.2f}%")


if __name__ == "__main__":
    main()
