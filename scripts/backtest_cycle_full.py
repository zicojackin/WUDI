from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crypto_trading_agents.cycle import (
    EXECUTION_MODES,
    CycleConfig,
    backtest_cycle,
    walk_forward_cycle,
)
from scripts.validate_data import validate_ohlcv_frame


BASE_URL = "https://data-api.binance.vision/api/v3/klines"
COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]


def fetch_klines(symbol: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
    start_ms = int(pd.Timestamp(start_date, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end_date, tz="UTC").timestamp() * 1000)
    cursor = start_ms
    rows: list[list[object]] = []

    while cursor < end_ms:
        response = requests.get(
            BASE_URL,
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            },
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        rows.extend(batch)
        cursor = int(batch[-1][6]) + 1
        if len(batch) < 1000:
            break

    frame = pd.DataFrame(rows, columns=COLUMNS)
    numeric_cols = ["open", "high", "low", "close", "volume"]
    frame[numeric_cols] = frame[numeric_cols].astype(float)
    frame["date"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True).dt.date
    return frame[["date", *numeric_cols]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-mode", choices=EXECUTION_MODES, default="daily")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--data-file")
    parser.add_argument("--start", default="2025-09-04")
    parser.add_argument("--end", default="2026-09-04")
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--stop-atr", type=float, default=2.0)
    parser.add_argument("--trail-atr", type=float, default=3.0)
    parser.add_argument("--exhaustion-atr", type=float, default=2.5)
    parser.add_argument("--partial-exit", type=float, default=0.0)
    parser.add_argument("--swing-window", type=int, default=3)
    parser.add_argument("--min-quality", type=float, default=40.0)
    parser.add_argument("--benchmark-symbol", default="BTCUSDT")
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--funding-rate-annual", type=float, default=0.10)
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument("--maintenance-margin", type=float, default=0.005)
    parser.add_argument("--max-position", type=float, default=1.0)
    parser.add_argument("--risk-per-trade", type=float, default=0.03)
    parser.add_argument("--min-setup-score", type=float, default=60.0)
    parser.add_argument("--use-exit-optimizer", action="store_true")
    parser.add_argument("--use-eth-fix", action="store_true")
    parser.add_argument("--use-eth-exit-v2", action="store_true")
    parser.add_argument("--recovery-multiplier", type=float, default=1.0)
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--train-days", type=int, default=180)
    parser.add_argument("--test-days", type=int, default=90)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    config = CycleConfig(
        execution_mode=args.execution_mode,
        fee_rate=args.fee,
        stop_atr_multiple=args.stop_atr,
        trail_atr_multiple=args.trail_atr,
        exhaustion_atr=args.exhaustion_atr,
        partial_exit_pct=args.partial_exit,
        swing_window=args.swing_window,
        min_pattern_quality=args.min_quality,
        slippage_rate=args.slippage,
        funding_rate_annual=args.funding_rate_annual,
        leverage=args.leverage,
        maintenance_margin_rate=args.maintenance_margin,
        max_position_fraction=args.max_position,
        risk_per_trade=args.risk_per_trade,
        min_setup_score=args.min_setup_score,
        use_exit_optimizer=args.use_exit_optimizer,
        use_eth_fix=args.use_eth_fix and args.symbol.upper() == "ETHUSDT",
        use_eth_exit_v2=args.use_eth_exit_v2 and args.symbol.upper() == "ETHUSDT",
        recovery_position_multiplier=args.recovery_multiplier,
    )
    if args.data_file:
        from scripts.validate_data import load_csv

        frame = load_csv(args.data_file).reset_index().rename(columns={"index": "date"})
        if isinstance(frame["date"].dtype, pd.DatetimeTZDtype):
            frame["date"] = frame["date"].dt.tz_localize(None)
    else:
        frame = fetch_klines(args.symbol, "1d", args.start, args.end)
    intraday_frame = fetch_klines(args.symbol, "4h", args.start, args.end)
    benchmark_symbol = (
        "ETHUSDT" if args.symbol.upper() == "BTCUSDT" else args.benchmark_symbol
    )
    benchmark_frame = fetch_klines(benchmark_symbol, "1d", args.start, args.end)
    validation = validate_ohlcv_frame(frame, args.symbol)
    if not validation["passed"]:
        raise SystemExit(f"数据校验失败: {validation['issues']}")
    result = backtest_cycle(
        frame,
        args.start,
        args.end,
        config,
        intraday_frame,
        benchmark_frame,
        symbol=args.symbol.upper(),
    )
    if args.walk_forward:
        result.walk_forward = walk_forward_cycle(
            frame,
            args.start,
            args.end,
            config,
            intraday_frame,
            benchmark_frame,
            train_days=args.train_days,
            test_days=args.test_days,
            symbol=args.symbol.upper(),
        )
    payload = asdict(result)
    if not args.full:
        payload.pop("equity_curve", None)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
