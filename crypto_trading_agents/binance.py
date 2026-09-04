from __future__ import annotations

from typing import Any

import requests


class BinanceError(RuntimeError):
    pass


class BinanceClient:
    """Public Binance spot market data client."""

    def __init__(
        self,
        base_url: str = "https://data-api.binance.vision",
        timeout: int = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = self.base_url + path
        try:
            response = requests.get(
                url,
                params=params,
                headers={"Accept": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            raise BinanceError(f"Unable to reach Binance at {url}: {exc}") from exc
        except ValueError as exc:
            raise BinanceError(f"Binance returned invalid JSON from {url}: {exc}") from exc

        if isinstance(result, dict) and result.get("code") not in (None, 0, "0"):
            raise BinanceError(f"Binance error {result.get('code')}: {result.get('msg')}")
        return result

    def ticker(self, inst_id: str) -> dict[str, Any]:
        symbol = normalize_binance_symbol(inst_id)
        raw = self._request("/api/v3/ticker/24hr", {"symbol": symbol})
        return {
            "instId": raw.get("symbol", symbol),
            "instType": "SPOT",
            "last": raw.get("lastPrice"),
            "open24h": raw.get("openPrice"),
            "high24h": raw.get("highPrice"),
            "low24h": raw.get("lowPrice"),
            "priceChangePercent": raw.get("priceChangePercent"),
            "vol24h": raw.get("volume"),
            "volCcy24h": raw.get("quoteVolume"),
            "bidPrice": raw.get("bidPrice"),
            "bidSz": raw.get("bidQty"),
            "askPrice": raw.get("askPrice"),
            "askSz": raw.get("askQty"),
        }

    def candles(self, inst_id: str, bar: str = "4H", limit: int = 200) -> list[dict[str, Any]]:
        symbol = normalize_binance_symbol(inst_id)
        rows = self._request(
            "/api/v3/klines",
            {"symbol": symbol, "interval": normalize_binance_interval(bar), "limit": limit},
        )
        return self._parse_candles(rows)

    def orderbook(self, inst_id: str, size: int = 50) -> dict[str, Any]:
        symbol = normalize_binance_symbol(inst_id)
        raw = self._request("/api/v3/depth", {"symbol": symbol, "limit": size})
        return {"bids": raw.get("bids", []), "asks": raw.get("asks", [])}

    @staticmethod
    def _parse_candles(rows: list[list[Any]]) -> list[dict[str, float]]:
        return [
            {
                "timestamp": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            for row in rows
        ]


def normalize_binance_symbol(inst_id: str) -> str:
    """Convert common instrument names such as ETH-USDT to Binance's ETHUSDT."""
    symbol = inst_id.upper().replace("-SWAP", "").replace("/", "").replace("-", "")
    if not symbol:
        raise BinanceError("Instrument ID is empty.")
    return symbol


def normalize_binance_interval(bar: str) -> str:
    if bar in {"1m", "3m", "5m", "15m", "30m"}:
        return bar
    interval = bar.upper()
    if interval.endswith("H"):
        return interval[:-1] + "h"
    if interval.endswith("D"):
        return interval[:-1] + "d"
    if interval.endswith("W"):
        return interval[:-1] + "w"
    return interval
