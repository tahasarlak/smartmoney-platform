from __future__ import annotations

import pytest

from app.live_strategy_pipeline import evaluate_live_smc


def _candles(count: int, start: int, interval: int):
    return [
        {
            "time": start + i * interval,
            "open": 100.0 + i,
            "high": 102.0 + i,
            "low": 99.0 + i,
            "close": 101.0 + i,
            "volume": 10.0,
        }
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_pipeline_fetches_all_timeframes_and_returns_latest_boundary_only(monkeypatch):
    import app.live_strategy_pipeline as module

    calls = []

    async def fake_fetch(symbol, timeframe, limit):
        calls.append((symbol, timeframe, limit))
        interval = {"4h": 14_400, "1h": 3_600, "15m": 900, "5m": 300, "1m": 60}[timeframe]
        return _candles(100, 1_700_000_000, interval)

    def fake_generate(symbol, candles, **kwargs):
        assert set(candles) == {"4h", "1h", "15m", "5m", "1m"}
        assert kwargs["use_regime_filter"] is True
        return {
            "status": "completed",
            "signal_count": 2,
            "signals": [
                {"signal_time": 1_700_000_000 + 99 * 300, "direction": "bullish"},
                {"signal_time": 1_700_000_000 + 100 * 300, "direction": "bearish"},
            ],
            "rejected_counts": {"regime_filter": 1},
            "market_regime_summary": {},
            "regime_filter": {"enabled": True},
            "lookahead_policy": {"future_bars_used_for_signal_generation": False},
        }

    monkeypatch.setattr(module, "generate_historical_smc_signals", fake_generate)
    result = await evaluate_live_smc(
        "btcusdt", fake_fetch, limit=100, decision_time=1_700_000_000 + 100 * 300
    )
    assert len(calls) == 5
    assert all(call[0] == "BTCUSDT" and call[2] == 100 for call in calls)
    assert result["latest_signal_count"] == 1
    assert result["signals"][0]["direction"] == "bearish"
    assert result["execution_allowed"] is False
    assert result["persistence"] == "not_written"


@pytest.mark.asyncio
async def test_pipeline_rejects_invalid_symbol():
    async def unused_fetch(*args):
        raise AssertionError("fetch must not be called")

    with pytest.raises(ValueError, match="Invalid symbol"):
        await evaluate_live_smc("BTC/USDT", unused_fetch)


@pytest.mark.asyncio
async def test_pipeline_rejects_invalid_limit():
    async def unused_fetch(*args):
        raise AssertionError("fetch must not be called")

    with pytest.raises(ValueError, match="limit must be between"):
        await evaluate_live_smc("BTCUSDT", unused_fetch, limit=50)


@pytest.mark.asyncio
async def test_pipeline_rejects_insufficient_5m_history():
    async def fake_fetch(symbol, timeframe, limit):
        return _candles(1, 1_700_000_000, 300)

    with pytest.raises(ValueError, match="At least two 5m candles"):
        await evaluate_live_smc("BTCUSDT", fake_fetch)


@pytest.mark.asyncio
async def test_pipeline_propagates_fetch_failure():
    async def fake_fetch(symbol, timeframe, limit):
        if timeframe == "1h":
            raise RuntimeError("provider unavailable")
        return _candles(100, 1_700_000_000, 300)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await evaluate_live_smc("BTCUSDT", fake_fetch, limit=100)


@pytest.mark.asyncio
async def test_pipeline_rejects_nonpositive_decision_time():
    async def fake_fetch(symbol, timeframe, limit):
        interval = {"4h": 14_400, "1h": 3_600, "15m": 900, "5m": 300, "1m": 60}[timeframe]
        return _candles(100, 1_700_000_000, interval)

    with pytest.raises(ValueError, match="decision_time must be positive"):
        await evaluate_live_smc("BTCUSDT", fake_fetch, limit=100, decision_time=0)
