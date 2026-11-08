import pytest

from app import market_data


@pytest.mark.asyncio
async def test_uses_fallback_host_after_418(monkeypatch):
    calls = []

    async def fake_request(host, symbol, interval, limit):
        calls.append(host)
        if host.endswith("api.binance.com"):
            raise market_data._RateLimitedHost(418, None, host)
        return [{"time": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]

    monkeypatch.setattr(market_data, "_request_host", fake_request)
    monkeypatch.setattr(market_data, "_hosts", lambda: ["https://api.binance.com", "https://data-api.binance.vision"])
    market_data._cache.clear()

    result = await market_data.binance_klines("BTCUSDT", "15m", 300)

    assert len(result) == 1
    assert calls == ["https://api.binance.com", "https://data-api.binance.vision"]


@pytest.mark.asyncio
async def test_uses_short_cache(monkeypatch):
    calls = 0

    async def fake_request(host, symbol, interval, limit):
        nonlocal calls
        calls += 1
        return [{"time": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]

    monkeypatch.setattr(market_data, "_request_host", fake_request)
    monkeypatch.setattr(market_data, "_hosts", lambda: ["https://data-api.binance.vision"])
    market_data._cache.clear()

    await market_data.binance_klines("ETHUSDT", "5m", 100)
    await market_data.binance_klines("ETHUSDT", "5m", 100)

    assert calls == 1


@pytest.mark.asyncio
async def test_does_not_retry_same_host_after_418(monkeypatch):
    calls = []

    async def fake_request(host, symbol, interval, limit):
        calls.append(host)
        raise market_data._RateLimitedHost(418, 120, host)

    monkeypatch.setattr(market_data, "_request_host", fake_request)
    monkeypatch.setattr(market_data, "_hosts", lambda: ["https://blocked.example"])
    market_data._cache.clear()

    with pytest.raises(market_data.MarketDataProviderError):
        await market_data.binance_klines("BTCUSDT", "15m", 300)

    assert calls == ["https://blocked.example"]
