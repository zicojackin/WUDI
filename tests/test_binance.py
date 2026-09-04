from crypto_trading_agents.binance import (
    normalize_binance_interval,
    normalize_binance_symbol,
)


def test_normalize_binance_symbol() -> None:
    assert normalize_binance_symbol("eth-usdt") == "ETHUSDT"
    assert normalize_binance_symbol("ETH/USDT") == "ETHUSDT"
    assert normalize_binance_symbol("BTC-USDT-SWAP") == "BTCUSDT"


def test_normalize_binance_interval() -> None:
    assert normalize_binance_interval("4H") == "4h"
    assert normalize_binance_interval("1D") == "1d"
    assert normalize_binance_interval("1W") == "1w"
    assert normalize_binance_interval("1M") == "1M"
