import uuid

from app.database import session_scope
from app.db_models import MarketPrice
from app.market_store import (
    add_watchlist_symbol,
    list_watchlist,
    remove_watchlist_symbol,
    upsert_market_price,
    list_market_prices,
)


def unique_symbol():
    return "T" + uuid.uuid4().hex[:10].upper()


def cleanup_symbol(symbol):
    with session_scope() as db:
        row = db.get(MarketPrice, symbol)
        if row is not None:
            db.delete(row)

    remove_watchlist_symbol(symbol)


def test_watchlist_and_prices_persist_across_store_calls():
    symbol = unique_symbol()

    try:
        assert symbol in add_watchlist_symbol(symbol)
        assert symbol in list_watchlist()

        upsert_market_price({
            "symbol": symbol,
            "price": 100.5,
            "event_time": "2026-01-01T00:00:00+00:00",
            "event_time_ms": 1767225600000,
        })

        prices = [
            item for item in list_market_prices()
            if item["symbol"] == symbol
        ]

        assert len(prices) == 1
        assert prices[0]["price"] == 100.5

    finally:
        cleanup_symbol(symbol)


def test_stale_price_event_does_not_overwrite_newer_tick():
    symbol = unique_symbol()

    try:
        base = {
            "symbol": symbol,
            "event_time": "2026-01-01T00:00:00+00:00",
        }

        upsert_market_price({
            **base,
            "price": 101,
            "event_time_ms": 200,
        })

        upsert_market_price({
            **base,
            "price": 99,
            "event_time_ms": 100,
        })

        prices = [
            item for item in list_market_prices()
            if item["symbol"] == symbol
        ]

        assert len(prices) == 1
        assert prices[0]["price"] == 101

    finally:
        cleanup_symbol(symbol)


def test_live_monitor_restores_watchlist_after_reconstruction():
    symbol = unique_symbol()

    try:
        from app.live_price_monitor import LivePriceMonitor

        first = LivePriceMonitor()
        first.add_symbol(symbol)

        second = LivePriceMonitor()

        assert symbol in second.watchlist_status()["symbols"]

    finally:
        cleanup_symbol(symbol)


def test_market_price_rejects_non_finite_values():
    symbol = unique_symbol()
    base = {
        "symbol": symbol,
        "event_time": "2026-01-01T00:00:00+00:00",
        "event_time_ms": 1767225600000,
    }

    for value in (float("nan"), float("inf"), float("-inf"), 0, -1):
        with pytest.raises(ValueError):
            upsert_market_price({**base, "price": value})
