from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
import requests


BASE_URL = "https://data-api.binance.vision/api/v3/klines"


def fetch_klines(symbol: str, interval: str, limit: int = 1000) -> pd.DataFrame:
    response = requests.get(
        BASE_URL,
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json()
    frame = pd.DataFrame(
        rows,
        columns=[
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
        ],
    )
    numeric_cols = ["open", "high", "low", "close", "volume", "quote_volume"]
    frame[numeric_cols] = frame[numeric_cols].astype(float)
    frame["date"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True).dt.date
    return frame


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["ema20"] = frame["close"].ewm(span=20, adjust=False).mean()
    frame["ema50"] = frame["close"].ewm(span=50, adjust=False).mean()
    frame["avg_volume20"] = frame["volume"].rolling(20).mean()
    high_low = frame["high"] - frame["low"]
    high_close = (frame["high"] - frame["close"].shift()).abs()
    low_close = (frame["low"] - frame["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    frame["atr20"] = true_range.rolling(20).mean()
    return frame


@dataclass(slots=True)
class Trade:
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    reason: str


def backtest(
    frame: pd.DataFrame,
    start_date: str,
    end_date: str,
    fee_rate: float,
    exhaustion_atr: float,
) -> dict[str, object]:
    data = add_indicators(frame).copy()
    data["date_str"] = data["date"].astype(str)
    period = data[(data["date_str"] >= start_date) & (data["date_str"] <= end_date)].copy()
    if period.empty:
        raise ValueError("No candles in the requested date range.")

    uptrend = (data["close"] > data["ema50"]) & (data["ema20"] > data["ema50"])
    pullback = data["close"].shift(1) < data["ema20"].shift(1)
    reclaim = data["close"] > data["ema20"]
    volume_confirm = data["volume"] > data["avg_volume20"].shift(1)
    entries = uptrend & pullback & reclaim & volume_confirm

    wedge_drop = data["close"] < data["ema50"]
    exhaustion = data["close"] > data["ema20"] + exhaustion_atr * data["atr20"]
    exits = wedge_drop | exhaustion

    trades: list[Trade] = []
    equity = 1.0
    equity_curve: list[float] = []
    in_position = False
    entry_price = 0.0
    entry_date = ""

    for _, row in period.iterrows():
        previous = int(row.name) - 1
        if not in_position and entries.loc[previous]:
            in_position = True
            entry_price = row["open"]
            entry_date = row["date_str"]
            equity *= 1 - fee_rate
        elif in_position and exits.loc[previous]:
            exit_price = row["open"]
            gross_return = exit_price / entry_price
            net_return = gross_return * (1 - fee_rate) ** 2
            equity *= net_return
            trades.append(
                Trade(
                    entry_date=entry_date,
                    entry_price=entry_price,
                    exit_date=row["date_str"],
                    exit_price=exit_price,
                    return_pct=(net_return - 1) * 100,
                    reason=(
                        "wedge_drop"
                        if wedge_drop.loc[previous]
                        else "exhaustion_extension"
                    ),
                )
            )
            in_position = False

        if in_position:
            equity_curve.append(equity * row["close"] / entry_price)
        else:
            equity_curve.append(equity)

    if in_position:
        last = period.iloc[-1]
        gross_return = last["close"] / entry_price
        net_return = gross_return * (1 - fee_rate) ** 2
        equity *= net_return
        trades.append(
            Trade(
                entry_date=entry_date,
                entry_price=entry_price,
                exit_date=str(last["date"]),
                exit_price=last["close"],
                return_pct=(net_return - 1) * 100,
                reason="open_at_end",
            )
        )

    first_open = float(period.iloc[0]["open"])
    last_close = float(period.iloc[-1]["close"])
    buy_and_hold = (last_close / first_open - 1) * 100
    strategy_return = (equity - 1) * 100

    equity_curve = pd.Series(equity_curve)
    drawdown = ((equity_curve / equity_curve.cummax()) - 1).min() * 100

    wins = sum(trade.return_pct > 0 for trade in trades)
    return {
        "symbol": "ETHUSDT",
        "interval": "1d",
        "start_date": start_date,
        "end_date": end_date,
        "strategy_return_pct": round(strategy_return, 2),
        "buy_and_hold_return_pct": round(buy_and_hold, 2),
        "trade_count": len(trades),
        "win_rate_pct": round(wins / len(trades) * 100, 2) if trades else 0,
        "max_drawdown_pct": round(drawdown, 2),
        "fee_rate": fee_rate,
        "exhaustion_atr": exhaustion_atr,
        "trades": [asdict(trade) for trade in trades],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--start", default="2025-09-04")
    parser.add_argument("--end", default="2026-09-04")
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--exhaustion-atr", type=float, default=2.0)
    args = parser.parse_args()

    frame = fetch_klines(args.symbol, "1d")
    result = backtest(frame, args.start, args.end, args.fee, args.exhaustion_atr)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
