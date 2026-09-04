"""Daily paper trading runner.

Fetches daily candles from OKX public API, evaluates strategy signals,
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
from crypto_trading_agents.okx import OkxClient, OkxError
from crypto_trading_agents.trend_base_simple import weekly_frame_from_daily


PAPER_DIR = PROJECT_ROOT / "paper_trading"
STATE_FILE = PAPER_DIR / "state.json"
TRADES_FILE = PAPER_DIR / "trades.jsonl"
LOOKBACK_BARS = 500
SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def fetch_daily_candles(client: OkxClient, symbol: str) -> pd.DataFrame:
    """Fetch daily candles from OKX with pagination to cover SMA200 + weekly EMA50."""
    okx_inst = symbol.replace("USDT", "-USDT")
    all_candles: list[dict] = []
    after: int | None = None

    while len(all_candles) < LOOKBACK_BARS:
        params: dict[str, object] = {"instId": okx_inst, "bar": "1D", "limit": 300}
        if after is not None:
            params["after"] = str(after)

        result = client._request("GET", "/api/v5/market/candles", params)
        raw = result.get("data", [])
        if not raw:
            break

        parsed = OkxClient._parse_candles(raw)
        all_candles = parsed + all_candles
        after = int(parsed[0]["timestamp"])

        if len(raw) < 300:
            break

    if not all_candles:
        raise OkxError(f"No candles returned for {symbol}")

    df = pd.DataFrame(all_candles[-LOOKBACK_BARS:])
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

    if result.open_position:
        return {
            "in_position": True,
            "entry_price": float(result.open_position["entry_price"]),
            "entry_date": result.open_position["entry_date"],
            "last_bar": end,
        }
    return {
        "in_position": False,
        "entry_price": 0.0,
        "entry_date": "",
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


def main() -> None:
    client = OkxClient()
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    any_trade = False

    for symbol in SYMBOLS:
        try:
            frame = fetch_daily_candles(client, symbol)
        except OkxError as exc:
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
            event = {
                "timestamp": now,
                "symbol": symbol,
                "action": action,
                "price": fill_price,
                "signal_date": last_bar,
                "pnl_pct": round(pnl_pct, 4),
            }
            if action == "open":
                event["exposure"] = current.get("target_exposure", "")
            log_trade(event)
            any_trade = True
            print(f"  {symbol}: {action.upper()} @ {fill_price:.2f} (pnl={pnl_pct:+.2%})")

        if is_in:
            entry = current["entry_price"]
            unrealized = (current_price / entry - 1.0) if entry > 0 else 0.0
            print(
                f"  {symbol}: HOLDING entry={entry:.2f} "
                f"current={current_price:.2f} unrealized={unrealized:+.2%}"
            )
        else:
            print(f"  {symbol}: FLAT")

        state[symbol] = current

    save_state(state)

    if not any_trade:
        print(f"\n  no position changes on {now[:10]}")


if __name__ == "__main__":
    main()
