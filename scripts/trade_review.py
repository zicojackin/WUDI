"""逐笔交易复盘与共性诊断。"""

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


def load_data(args: argparse.Namespace) -> pd.DataFrame:
    if args.data_file:
        return pd.read_csv(args.data_file)
    return fetch_klines(args.symbol, "1d", args.start, args.end)


def review_trades(trades: list, symbol: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"{symbol} 逐笔交易复盘 ({len(trades)} 笔)")
    print(f"{'=' * 70}")

    for index, trade in enumerate(trades, start=1):
        status = "WIN" if trade.return_pct > 0 else "LOSS"
        print(f"\n[{index}] {status} {trade.entry_date} -> {trade.exit_date}")
        print(
            f"    entry={trade.entry_price:.2f} exit={trade.exit_price:.2f} "
            f"pnl={trade.return_pct:+.2f}%"
        )
        print(
            f"    hold={trade.bars_held}d reason={trade.exit_reason} "
            f"stage={trade.entry_stage} state={trade.cycle_state}"
        )
        print(
            f"    setup={trade.setup_score:.1f} quality={trade.pattern_quality:.1f} "
            f"fraction={trade.position_fraction:.1%}"
        )
        print(
            f"    MFE={trade.max_favorable_excursion_pct:+.2f}% "
            f"MAE={trade.max_adverse_excursion_pct:+.2f}%"
        )
        if trade.return_pct > 0 and trade.max_favorable_excursion_pct > 0:
            capture_ratio = trade.return_pct / trade.max_favorable_excursion_pct
            if capture_ratio < 0.5:
                print("    NOTE: profit capture < 50%, possible early exit")
        if trade.return_pct <= 0 and trade.max_favorable_excursion_pct >= 3:
            print("    NOTE: trade had >=3% favorable move but closed as a loss")

    wins = [trade.return_pct for trade in trades if trade.return_pct > 0]
    losses = [trade.return_pct for trade in trades if trade.return_pct <= 0]
    print(f"\n{'=' * 70}")
    print("汇总")
    print(f"{'=' * 70}")
    print(f"盈利交易: {len(wins)} 笔, 平均 {sum(wins) / len(wins):+.2f}%" if wins else "盈利交易: 0 笔")
    print(f"亏损交易: {len(losses)} 笔, 平均 {sum(losses) / len(losses):+.2f}%" if losses else "亏损交易: 0 笔")

    for field_name, getter in [
        ("exit_reason", lambda trade: trade.exit_reason),
        ("entry_stage", lambda trade: trade.entry_stage),
        ("cycle_state", lambda trade: trade.cycle_state),
    ]:
        groups: dict[str, list[float]] = {}
        for trade in trades:
            groups.setdefault(getter(trade), []).append(trade.return_pct)
        print(f"\n按 {field_name}:")
        for key, values in sorted(groups.items(), key=lambda item: sum(item[1]), reverse=True):
            print(f"  {key}: {len(values)} 笔, 合计 {sum(values):+.2f}%, 平均 {sum(values) / len(values):+.2f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="逐笔交易复盘")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-09-04")
    parser.add_argument("--data-file")
    parser.add_argument("--risk-per-trade", type=float, default=0.03)
    parser.add_argument("--min-setup-score", type=float, default=60.0)
    args = parser.parse_args()

    symbol = args.symbol.upper()
    frame = load_data(args)
    config = CycleConfig(
        risk_per_trade=args.risk_per_trade,
        min_setup_score=args.min_setup_score,
    )
    result = backtest_cycle(frame, args.start, args.end, config, symbol=symbol)
    review_trades(result.trades, symbol)


if __name__ == "__main__":
    main()
