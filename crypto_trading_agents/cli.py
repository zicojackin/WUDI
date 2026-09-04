from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .binance import BinanceClient
from .config import Settings
from .pipeline import run_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto-agents",
        description="Multi-agent crypto market research using Binance spot data and optional OKX derivatives data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Run the full agent pipeline.")
    analyze.add_argument("instrument", help="Instrument ID, e.g. BTC-USDT.")
    analyze.add_argument("--bar", default="4H", help="Candle interval, e.g. 1H, 4H, 1D.")
    analyze.add_argument("--limit", type=int, default=200, help="Number of candles to fetch.")
    analyze.add_argument("--swap", action="store_true", help="Also fetch funding rate and open interest.")
    analyze.add_argument("--account", action="store_true", help="Also read private balance and positions.")
    analyze.add_argument("--no-news", action="store_true", help="Disable RSS news fetching.")
    analyze.add_argument("--no-sentiment", action="store_true", help="Disable Fear & Greed Index fetching.")
    analyze.set_defaults(func=_run_analyze)

    data = subparsers.add_parser("data", help="Print a compact market data snapshot.")
    data.add_argument("instrument", help="Instrument ID, e.g. BTC-USDT.")
    data.add_argument("--bar", default="4H")
    data.add_argument("--limit", type=int, default=30)
    data.set_defaults(func=_run_data)

    return parser


def _run_analyze(args: argparse.Namespace) -> int:
    try:
        result = run_analysis(
            inst_id=args.instrument,
            bar=args.bar,
            limit=args.limit,
            swap=args.swap,
            account=args.account,
            include_news=not args.no_news,
            include_sentiment=not args.no_sentiment,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_data(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    client = BinanceClient(
        base_url=settings.binance_base_url,
        timeout=settings.binance_timeout,
    )
    try:
        ticker = client.ticker(args.instrument)
        candles = client.candles(args.instrument, bar=args.bar, limit=args.limit)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    payload: dict[str, Any] = {
        "instrument": args.instrument,
        "ticker": ticker,
        "candles": candles,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
