from __future__ import annotations

import math
from typing import Any, Iterable, Sequence


def sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = value * alpha + result * (1 - alpha)
    return result


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, current in zip(closes[-(period + 1) :], closes[-period:]):
        change = current - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, float | None]:
    if len(closes) < slow + signal:
        return {"macd": None, "signal": None, "histogram": None}
    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)][-(signal + 1) :]
    signal_line = _ema_series(macd_line, signal)
    current_macd = macd_line[-1]
    current_signal = signal_line[-1]
    return {
        "macd": current_macd,
        "signal": current_signal,
        "histogram": current_macd - current_signal,
    }


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    alpha = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for value in values[period:]:
        result.append(value * alpha + result[-1] * (1 - alpha))
    return result


def atr(candles: Sequence[dict[str, float]], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    true_ranges: list[float] = []
    for prev, current in zip(candles[-(period + 1) :], candles[-period:]):
        high_low = current["high"] - current["low"]
        high_close = abs(current["high"] - prev["close"])
        low_close = abs(current["low"] - prev["close"])
        true_ranges.append(max(high_low, high_close, low_close))
    return sum(true_ranges) / period


def bollinger_bands(closes: Sequence[float], period: int = 20, std_dev: float = 2.0) -> dict[str, float | None]:
    if len(closes) < period:
        return {"middle": None, "upper": None, "lower": None}
    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((value - middle) ** 2 for value in window) / period
    deviation = math.sqrt(variance)
    return {
        "middle": middle,
        "upper": middle + deviation * std_dev,
        "lower": middle - deviation * std_dev,
    }


def volume_zscore(volumes: Sequence[float], period: int = 20) -> float | None:
    if len(volumes) < period + 1:
        return None
    window = volumes[-(period + 1) : -1]
    mean = sum(window) / period
    variance = sum((value - mean) ** 2 for value in window) / period
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (volumes[-1] - mean) / std


def orderbook_imbalance(orderbook: dict[str, Any], depth: int = 20) -> dict[str, float | None]:
    bids = orderbook.get("bids", [])[:depth]
    asks = orderbook.get("asks", [])[:depth]
    if not bids or not asks:
        return {"ratio": None, "bid_volume": None, "ask_volume": None}
    bid_volume = sum(float(row[1]) for row in bids)
    ask_volume = sum(float(row[1]) for row in asks)
    return {
        "ratio": bid_volume / ask_volume if ask_volume else None,
        "bid_volume": bid_volume,
        "ask_volume": ask_volume,
    }


def technical_snapshot(candles: Sequence[dict[str, float]]) -> dict[str, Any]:
    closes = [row["close"] for row in candles]
    volumes = [row["volume"] for row in candles]
    current_price = closes[-1] if closes else None
    return {
        "price": current_price,
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "sma200": sma(closes, 200),
        "rsi14": rsi(closes, 14),
        "macd": macd(closes),
        "atr14": atr(candles, 14),
        "bollinger20": bollinger_bands(closes, 20),
        "volume_zscore": volume_zscore(volumes, 20),
        "change_1": _pct_change(closes, 1),
        "change_10": _pct_change(closes, 10),
        "change_50": _pct_change(closes, 50),
    }


def _pct_change(values: Sequence[float], periods: int) -> float | None:
    if len(values) <= periods:
        return None
    previous = values[-periods - 1]
    return (values[-1] - previous) / previous * 100


def score_technicals(snapshot: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    price = snapshot.get("price")
    ema20 = snapshot.get("ema20")
    ema50 = snapshot.get("ema50")
    sma200 = snapshot.get("sma200")
    rsi_value = snapshot.get("rsi14")
    macd_data = snapshot.get("macd", {})
    bollinger = snapshot.get("bollinger20", {})
    volume_z = snapshot.get("volume_zscore")

    if price and ema20 and price > ema20:
        score += 1
        reasons.append("价格高于 EMA20")
    if ema20 and ema50 and ema20 > ema50:
        score += 1
        reasons.append("EMA20 位于 EMA50 上方")
    if price and sma200 and price > sma200:
        score += 1
        reasons.append("价格高于 SMA200")
    if isinstance(rsi_value, (int, float)):
        if rsi_value >= 70:
            score -= 1
            reasons.append(f"RSI {rsi_value:.1f} 超买")
        elif rsi_value <= 30:
            score += 1
            reasons.append(f"RSI {rsi_value:.1f} 超卖")
        elif rsi_value > 55:
            score += 1
            reasons.append(f"RSI {rsi_value:.1f} 偏多")
        elif rsi_value < 45:
            score -= 1
            reasons.append(f"RSI {rsi_value:.1f} 偏空")
    macd_value = macd_data.get("macd")
    signal_value = macd_data.get("signal")
    if macd_value is not None and signal_value is not None:
        if macd_value > signal_value:
            score += 1
            reasons.append("MACD 高于信号线")
        else:
            score -= 1
            reasons.append("MACD 低于信号线")
    if price and bollinger.get("upper") and price > bollinger["upper"]:
        score -= 1
        reasons.append("价格突破 Bollinger 上轨")
    if price and bollinger.get("lower") and price < bollinger["lower"]:
        score += 1
        reasons.append("价格跌破 Bollinger 下轨")
    if volume_z is not None and abs(volume_z) >= 2:
        reasons.append(f"成交量 z-score {volume_z:.2f}，注意异常波动")
    return score, reasons
