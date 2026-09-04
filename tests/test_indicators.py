import math

from crypto_trading_agents.indicators import (
    ema,
    macd,
    rsi,
    sma,
    technical_snapshot,
)


def test_sma_and_ema() -> None:
    values = [1, 2, 3, 4, 5]
    assert sma(values, 5) == 3.0
    assert ema(values, 3) == 4.0


def test_rsi_bounds() -> None:
    up = [float(i) for i in range(1, 30)]
    assert rsi(up) == 100.0


def test_macd_returns_values_for_enough_data() -> None:
    values = [float(i % 7) for i in range(60)]
    result = macd(values)
    assert result["macd"] is not None
    assert result["signal"] is not None
    assert result["histogram"] is not None


def test_technical_snapshot_has_price() -> None:
    candles = [
        {
            "timestamp": i,
            "open": float(i),
            "high": float(i + 1),
            "low": float(i - 1),
            "close": float(i),
            "volume": 10.0,
        }
        for i in range(1, 60)
    ]
    result = technical_snapshot(candles)
    assert result["price"] == 59.0
    assert math.isfinite(result["rsi14"])
