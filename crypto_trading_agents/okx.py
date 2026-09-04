from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


class OkxError(RuntimeError):
    pass


class OkxClient:
    def __init__(
        self,
        base_url: str = "https://www.okx.com",
        timeout: int = 20,
        config_path: Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.config_path = config_path

    def _config(self) -> dict[str, Any]:
        if not self.config_path or not self.config_path.exists():
            return {}
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - user config errors
            raise OkxError(f"Unable to read OKX config {self.config_path}: {exc}") from exc

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        private: bool = False,
    ) -> dict[str, Any]:
        query = ""
        if params:
            from urllib.parse import urlencode

            query = "?" + urlencode(params)
        request_path = path + query
        url = self.base_url + request_path
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "crypto-trading-agents/0.1",
        }
        payload = None
        if private:
            cfg = self._config()
            api_key = os.getenv("OKX_API_KEY", cfg.get("apiKey", ""))
            secret_key = os.getenv("OKX_SECRET_KEY", cfg.get("secretKey", ""))
            passphrase = os.getenv("OKX_PASSPHRASE", cfg.get("passphrase", ""))
            if not all([api_key, secret_key, passphrase]):
                raise OkxError(
                    "Private OKX access requires OKX_API_KEY, OKX_SECRET_KEY and "
                    "OKX_PASSPHRASE, or a valid OKX_CONFIG_PATH."
                )
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            body_text = json.dumps(body) if body is not None else ""
            sign_input = f"{timestamp}{method}{request_path}{body_text}".encode()
            signature = base64.b64encode(
                hmac.new(secret_key.encode(), sign_input, hashlib.sha256).digest()
            ).decode()
            headers.update(
                {
                    "OK-ACCESS-KEY": api_key,
                    "OK-ACCESS-SIGN": signature,
                    "OK-ACCESS-TIMESTAMP": timestamp,
                    "OK-ACCESS-PASSPHRASE": passphrase,
                    "Content-Type": "application/json",
                }
            )
            payload = body_text.encode() if body is not None else None

        try:
            response = requests.request(
                method,
                url,
                params=None if query else params,
                data=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            raise OkxError(f"Unable to reach OKX at {url}: {exc}") from exc
        except ValueError as exc:
            raise OkxError(f"OKX returned invalid JSON from {url}: {exc}") from exc

        if result.get("code") not in (None, "0"):
            raise OkxError(f"OKX error {result.get('code')}: {result.get('msg')}")
        return result

    def ticker(self, inst_id: str) -> dict[str, Any]:
        return self._single(self._request("GET", "/api/v5/market/ticker", {"instId": inst_id}))

    def candles(self, inst_id: str, bar: str = "4H", limit: int = 200) -> list[dict[str, Any]]:
        raw = self._request(
            "GET",
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": bar, "limit": limit},
        ).get("data", [])
        return self._parse_candles(raw)

    def orderbook(self, inst_id: str, size: int = 50) -> dict[str, Any]:
        return self._single(self._request("GET", "/api/v5/market/books", {"instId": inst_id, "sz": size}))

    def funding_rate(self, inst_id: str) -> dict[str, Any] | None:
        try:
            return self._single(self._request("GET", "/api/v5/public/funding-rate", {"instId": inst_id}))
        except OkxError:
            return None

    def open_interest(self, inst_id: str) -> dict[str, Any] | None:
        try:
            return self._single(self._request("GET", "/api/v5/public/open-interest", {"instId": inst_id}))
        except OkxError:
            return None

    def balance(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/api/v5/account/balance", private=True)
        return result.get("data", [])

    def positions(self, inst_id: str | None = None) -> list[dict[str, Any]]:
        params = {"instId": inst_id} if inst_id else None
        result = self._request("GET", "/api/v5/account/positions", params, private=True)
        return result.get("data", [])

    @staticmethod
    def _single(result: dict[str, Any]) -> dict[str, Any]:
        data = result.get("data", [])
        if not data:
            raise OkxError("OKX returned an empty data set.")
        return data[0]

    @staticmethod
    def _parse_candles(rows: list[list[str]]) -> list[dict[str, float]]:
        parsed: list[dict[str, float]] = []
        for row in reversed(rows):
            parsed.append(
                {
                    "timestamp": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        return parsed
