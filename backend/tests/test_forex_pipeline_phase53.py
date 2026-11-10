from datetime import datetime, timezone
import pytest

from app.forex_intraday import CandleAggregator, SYMBOLS, validate_tick
from app.forex_paper import quote_to_usd, _adverse_fill
from app.forex_history import aggregate_m1


def test_eight_required_symbols_are_configured():
    assert set(SYMBOLS) == {
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
        "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD",
    }


def test_tick_validation_normalizes_provider_symbol():
    tick = validate_tick({"symbol": "EUR/USD", "price": "1.08", "timestamp": 1_800_000_000})
    assert tick["symbol"] == "EURUSD"
    assert tick["price"] == 1.08
    assert tick["event_time_ms"] == 1_800_000_000_000


def test_tick_validation_rejects_unsupported_symbol_and_bad_price():
    with pytest.raises(ValueError):
        validate_tick({"symbol": "BTC/USD", "price": 100, "timestamp": 1_800_000_000})
    with pytest.raises(ValueError):
        validate_tick({"symbol": "EUR/USD", "price": 0, "timestamp": 1_800_000_000})


def test_aggregator_emits_only_real_closed_bars_and_does_not_fill_gaps():
    agg = CandleAggregator()
    first = {"symbol": "EURUSD", "price": 1.1, "event_time_ms": 1_800_000_000_000}
    assert agg.update(first) == []
    second = {"symbol": "EURUSD", "price": 1.2, "event_time_ms": 1_800_000_300_000}
    closed = agg.update(second)
    five = [x for x in closed if x["timeframe"] == "5m"]
    assert len(five) == 1
    assert five[0]["open"] == 1.1
    assert five[0]["high"] == 1.1
    assert five[0]["close"] == 1.1
    # The 5-minute gap is not backfilled with synthetic candles.
    gap_close = agg.update({"symbol": "EURUSD", "price": 1.3,
                            "event_time_ms": 1_800_000_900_000})
    five_times = [x["time"] for x in gap_close if x["timeframe"] == "5m"]
    assert five_times == [1_800_000_300]


def test_quote_currency_conversion_for_usd_quoted_and_non_usd_quoted_pairs():
    assert quote_to_usd("EURUSD", {}) == 1.0
    assert quote_to_usd("XAUUSD", {}) == 1.0
    assert quote_to_usd("USDJPY", {"USDJPY": 150.0}) == pytest.approx(1 / 150)
    assert quote_to_usd("USDCHF", {"USDCHF": 0.9}) == pytest.approx(1 / 0.9)
    assert quote_to_usd("USDCAD", {"USDCAD": 1.35}) == pytest.approx(1 / 1.35)


def test_quote_conversion_fails_closed_without_conversion_quote():
    with pytest.raises(ValueError):
        quote_to_usd("USDJPY", {})


def test_spread_and_slippage_are_applied_adversely():
    long_entry = _adverse_fill(1.1, "bullish", True, 10, 2)
    long_exit = _adverse_fill(1.1, "bullish", False, 10, 2)
    short_entry = _adverse_fill(1.1, "bearish", True, 10, 2)
    short_exit = _adverse_fill(1.1, "bearish", False, 10, 2)
    assert long_entry > 1.1
    assert long_exit < 1.1
    assert short_entry < 1.1
    assert short_exit > 1.1


def test_m1_resampling_requires_complete_contiguous_buckets():
    rows = [
        {"time": 1_800_000_000 + i * 60, "open": 1 + i/10000,
         "high": 1.01 + i/10000, "low": .99 + i/10000,
         "close": 1 + i/10000, "volume": 0.0}
        for i in range(5)
    ]
    frames = aggregate_m1(rows)
    assert len(frames["1m"]) == 5
    assert len(frames["5m"]) == 1
    assert frames["5m"][0]["open"] == rows[0]["open"]
    assert frames["5m"][0]["close"] == rows[-1]["close"]
    assert frames["5m"][0]["high"] == max(x["high"] for x in rows)
    assert frames["5m"][0]["low"] == min(x["low"] for x in rows)


def test_m1_resampling_does_not_invent_missing_minute():
    rows = [
        {"time": 1_800_000_000 + i * 60, "open": 1.1, "high": 1.2,
         "low": 1.0, "close": 1.1, "volume": 0.0}
        for i in (0, 1, 3, 4)
    ]
    assert aggregate_m1(rows)["5m"] == []


def test_aggregator_ignores_out_of_order_tick_inside_same_bucket():
    agg = CandleAggregator()
    start = 1_800_000_000_000
    agg.update({"symbol": "EURUSD", "price": 1.10, "event_time_ms": start})
    agg.update({"symbol": "EURUSD", "price": 1.11, "event_time_ms": start + 60_000})
    agg.update({"symbol": "EURUSD", "price": 1.09, "event_time_ms": start + 30_000})
    current = agg.current[("EURUSD", "5m")]
    assert current["close"] == 1.11
    assert current["low"] == 1.10
