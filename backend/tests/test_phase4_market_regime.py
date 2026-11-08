from __future__ import annotations

import math

import pytest

from app.market_regime import analyze_market_regime
from app.scanner import scan_symbol


def make_candles(kind: str, count: int = 90, interval: int = 300):
    rows = []
    price = 100.0
    for index in range(count):
        if kind == "trend":
            next_price = price + 0.35
            spread = 0.08
        elif kind == "range":
            next_price = price + (0.4 if index % 2 == 0 else -0.4)
            spread = 0.12
        elif kind == "expanded":
            next_price = price + 0.05
            spread = 0.8 if index >= count - 12 else 0.1
        else:
            next_price = price + 0.05
            spread = 0.1
        rows.append({
            "time": index * interval,
            "open": price,
            "high": max(price, next_price) + spread,
            "low": min(price, next_price) - spread,
            "close": next_price,
            "volume": 30.0 if index == count - 2 else 10.0,
        })
        price = next_price
    return rows


def test_regime_uses_closed_candles_only():
    rows = make_candles("trend")
    baseline = analyze_market_regime(rows, "5m")
    rows[-1]["high"] = 1e12
    rows[-1]["low"] = 1e-9
    changed_forming = analyze_market_regime(rows, "5m")
    assert baseline == changed_forming
    assert baseline["closed_candle_only"] is True


def test_regime_detects_directional_trend_and_range():
    trend = analyze_market_regime(make_candles("trend"), "1h")
    ranging = analyze_market_regime(make_candles("range"), "1h")
    assert trend["regime"] == "trending"
    assert trend["trend_direction"] == "bullish"
    assert ranging["regime"] in ("ranging", "transition")
    assert ranging["trend_direction"] == "neutral"


def test_regime_reports_expanded_volatility_and_volume_participation():
    result = analyze_market_regime(make_candles("expanded"), "15m")
    assert result["volatility_regime"] == "expanded"
    assert result["volume_participation"] == "high"
    assert result["estimated_win_probability"] is None


def test_regime_rejects_non_finite_market_data():
    rows = make_candles("trend")
    rows[-2]["close"] = math.nan
    with pytest.raises(ValueError, match="Non-finite"):
        analyze_market_regime(rows, "5m")


def test_scanner_exposes_auditable_score_breakdown():
    intervals = {"4h": 14400, "1h": 3600, "15m": 900, "5m": 300, "1m": 60}
    candles = {tf: make_candles("trend", interval=intervals[tf]) for tf in intervals}
    analyses = {
        tf: {
            "structure": "bullish" if tf in ("4h", "1h", "15m") else "range",
            "events": [],
            "zones": [],
        }
        for tf in intervals
    }
    result = scan_symbol("TESTUSDT", candles, analyses, {"min_quality_score": 0})
    bullish = next(item for item in result["scenarios"] if item["direction"] == "bullish")
    bearish = next(item for item in result["scenarios"] if item["direction"] == "bearish")
    assert bullish["score_breakdown"] == {
        "base": 25,
        "higher_timeframe_alignment": 18,
        "15m_structure": 8,
    }
    assert bullish["quality_score"] == 51
    assert bearish["score_breakdown"]["counter_trend_penalty"] == -8


def test_v4_market_regime_endpoint_returns_all_timeframes(monkeypatch):
    import asyncio
    from app import main

    now = 1_800_000_000
    intervals = {"4h": 14400, "1h": 3600, "15m": 900, "5m": 300, "1m": 60}

    # Replace candle timestamps with a recent, valid Binance-style series.
    async def recent_klines(symbol, timeframe, limit):
        rows = make_candles("trend", count=101, interval=intervals[timeframe])
        start = now - intervals[timeframe] * 101
        for index, row in enumerate(rows):
            row["time"] = start + index * intervals[timeframe]
        return rows

    monkeypatch.setattr(main, "binance_klines", recent_klines)
    monkeypatch.setattr(main.time, "time", lambda: now)
    result = asyncio.run(main.v4_market_regime("BTCUSDT", 100))
    assert set(result["market_regime"]) == set(intervals)
    assert result["methodology_version"] == "market-regime-1.0"
    assert result["execution_allowed"] is False
