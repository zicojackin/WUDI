from crypto_trading_agents.binance import drop_unclosed_klines


def test_drop_unclosed_klines() -> None:
    now = 1_800_000_000_000
    closed = {"timestamp": 0, "close_time": now - 1}
    open_bar = {"timestamp": 0, "close_time": now + 86_399_999}
    assert drop_unclosed_klines([closed, open_bar], now_ms=now) == [closed]
    assert drop_unclosed_klines([closed], now_ms=now) == [closed]
