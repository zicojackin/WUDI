"""Daily paper trading runner.

Fetches daily candles from Binance public API, evaluates strategy signals,
and logs position changes to a local JSON Lines file.

Usage:
    python scripts/paper_trading.py

Run once per day after the daily candle closes (after 00:00 UTC).
State is persisted in paper_trading/state.json; trades are appended
to paper_trading/trades.jsonl.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crypto_trading_agents.cycle import CycleConfig, backtest_cycle, prepare_cycle_frame
from crypto_trading_agents.eth_strategy_v3 import ETHStrategyV3, ETHStrategyV3Config
from crypto_trading_agents.binance import (
    BinanceClient,
    BinanceError,
    drop_unclosed_klines,
)
from crypto_trading_agents.trend_base_simple import weekly_frame_from_daily


PAPER_DIR = PROJECT_ROOT / "paper_trading"
STATE_FILE = PAPER_DIR / "state.json"
TRADES_FILE = PAPER_DIR / "trades.jsonl"
LOOKBACK_BARS = 500
SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def fetch_daily_candles(client: BinanceClient, symbol: str) -> pd.DataFrame:
    """Fetch daily candles from Binance public data API."""
    raw = client.candles(symbol, bar="1d", limit=LOOKBACK_BARS)
    if not raw:
        raise BinanceError(f"No candles returned for {symbol}")

    raw = drop_unclosed_klines(raw)
    df = pd.DataFrame(raw)
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def evaluate_btc(frame: pd.DataFrame) -> dict:
    """Run BTC cycle engine and return the position state at the latest bar."""
    config = CycleConfig(
        execution_mode="daily",
        risk_per_trade=0.03,
        use_btc_exit_final=True,
    )
    start = str(frame["date"].iloc[0].date())
    end = str(frame["date"].iloc[-1].date())
    result = backtest_cycle(frame, start, end, config, symbol="BTCUSDT")

    exit_reason = ""
    stop_price = 0.0
    if result.trades:
        last_trade = result.trades[-1]
        exit_reason = last_trade.exit_reason
        stop_price = float(last_trade.initial_stop)

    if result.open_position:
        return {
            "in_position": True,
            "entry_price": float(result.open_position["entry_price"]),
            "entry_date": result.open_position["entry_date"],
            "pattern_quality": float(result.open_position.get("pattern_quality", 0.0)),
            "setup_score": float(result.open_position.get("setup_score", 0.0)),
            "stop_price": float(result.open_position.get("stop", 0.0)),
            "last_bar": end,
        }
    return {
        "in_position": False,
        "entry_price": 0.0,
        "entry_date": "",
        "exit_reason": exit_reason,
        "stop_price": stop_price,
        "last_bar": end,
    }


def evaluate_eth(frame: pd.DataFrame) -> dict:
    """Run ETH V3 strategy and return the position state at the latest bar."""
    prepared = prepare_cycle_frame(frame, CycleConfig(), symbol="ETHUSDT")
    weekly = weekly_frame_from_daily(frame)
    weekly_index = {date.date(): row for date, row in weekly.iterrows()}

    strategy = ETHStrategyV3(ETHStrategyV3Config())
    last_open_date = ""
    last_open_price = 0.0

    for row in prepared.itertuples(index=False):
        bar = row._asdict()
        current_date = pd.Timestamp(bar["date"])
        action = strategy.on_bar(bar, weekly_index.get(current_date.date()))
        if action.base_action == "open":
            last_open_date = str(current_date.date())
            last_open_price = float(bar["close"])

    latest_close = float(prepared["close"].iloc[-1])
    latest_date = str(prepared["date"].iloc[-1].date())

    return {
        "in_position": strategy.base_open,
        "entry_price": last_open_price,
        "entry_date": last_open_date,
        "target_exposure": strategy.target_exposure,
        "current_price": latest_close,
        "last_bar": latest_date,
    }


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    PAPER_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def log_trade(event: dict) -> None:
    PAPER_DIR.mkdir(exist_ok=True)
    with TRADES_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


def has_daily_state(symbol: str, signal_date: str) -> bool:
    """Check if a daily_state for (symbol, signal_date) is already logged."""
    if not TRADES_FILE.exists():
        return False
    with TRADES_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                row.get("event") == "daily_state"
                and row.get("symbol") == symbol
                and row.get("signal_date") == signal_date
            ):
                return True
    return False


def log_daily_state(
    now: str, symbol: str, last_bar: str, current_price: float,
    in_position: bool, entry_price: float,
) -> None:
    if has_daily_state(symbol, last_bar):
        return
    unrealized = (current_price / entry_price - 1.0) if entry_price > 0 else 0.0
    event = {
        "v": 1,
        "event": "daily_state",
        "timestamp": now,
        "symbol": symbol,
        "signal_date": last_bar,
        "current_price": current_price,
        "in_position": in_position,
        "entry_price": entry_price,
        "unrealized_pnl_pct": round(unrealized, 6) if in_position else None,
    }
    log_trade(event)


def main() -> None:
    client = BinanceClient()
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    any_trade = False

    for symbol in SYMBOLS:
        try:
            frame = fetch_daily_candles(client, symbol)
        except BinanceError as exc:
            print(f"  {symbol}: fetch failed ({exc})", file=sys.stderr)
            continue

        if symbol == "BTCUSDT":
            current = evaluate_btc(frame)
            current_price = float(frame["close"].iloc[-1])
        else:
            current = evaluate_eth(frame)
            current_price = current.get("current_price", float(frame["close"].iloc[-1]))

        prev = state.get(symbol, {})
        was_in = prev.get("in_position", False)
        is_in = current["in_position"]
        last_bar = current.get("last_bar", "")

        if last_bar and prev.get("last_bar") == last_bar:
            print(f"  {symbol}: no new bar (last={last_bar}), skipping")
            log_daily_state(
                now, symbol, last_bar, current_price,
                current["in_position"], current["entry_price"],
            )
            continue

        if not was_in and is_in:
            action = "open"
            fill_price = current["entry_price"]
            pnl_pct = 0.0
        elif was_in and not is_in:
            action = "close"
            fill_price = current_price
            entry = float(prev.get("entry_price", 0.0))
            pnl_pct = (fill_price / entry - 1.0) if entry > 0 else 0.0
        else:
            action = None

        if action:
            entry_price = current["entry_price"] if action == "open" else float(prev.get("entry_price", 0.0))
            event = {
                "v": 1,
                "timestamp": now,
                "symbol": symbol,
                "action": action,
                "price": fill_price,
                "signal_date": last_bar,
                "pnl_pct": round(pnl_pct, 4),
            }
            if action == "open":
                event["exposure"] = current.get("target_exposure", "")
                event["grade_at_entry"] = current.get("setup_score", "")
                event["pattern_quality"] = current.get("pattern_quality", "")
                current["origin"] = "backtest_carry" if not prev else "paper_trading"
                event["origin"] = current["origin"]
            if action == "close":
                entry_date = prev.get("entry_date", "")
                holding_days = 0
                if entry_date:
                    try:
                        holding_days = (pd.Timestamp(last_bar) - pd.Timestamp(entry_date)).days
                    except Exception:
                        pass
                event["entry_price"] = entry_price
                event["entry_date"] = entry_date
                event["holding_days"] = holding_days
                event["exit_reason"] = prev.get("exit_reason", "")
                event["stop_price"] = prev.get("stop_price", 0.0)
                event["origin"] = prev.get("origin", "backtest_carry")
            log_trade(event)
            any_trade = True
            print(f"  {symbol}: {action.upper()} @ {fill_price:.2f} (pnl={pnl_pct:+.2%})")

        if is_in:
            if "origin" not in current:
                current["origin"] = prev.get("origin", "backtest_carry")
            entry = current["entry_price"]
            unrealized = (current_price / entry - 1.0) if entry > 0 else 0.0
            print(
                f"  {symbol}: HOLDING entry={entry:.2f} "
                f"current={current_price:.2f} unrealized={unrealized:+.2%}"
            )
        else:
            print(f"  {symbol}: FLAT")

        log_daily_state(
            now, symbol, last_bar, current_price,
            is_in, current["entry_price"],
        )
        state[symbol] = current

    save_state(state)

    if not any_trade:
        print(f"\n  no position changes on {now[:10]}")


if __name__ == "__main__":
    main()
