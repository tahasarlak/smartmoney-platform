from app.market_store import (
    add_watchlist_symbol, list_watchlist, remove_watchlist_symbol,
    upsert_market_price, list_market_prices,
)


def test_watchlist_and_prices_persist_across_store_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_STATE_DB", str(tmp_path / "market.sqlite3"))
    assert add_watchlist_symbol("BTCUSDT") == ["BTCUSDT"]
    assert add_watchlist_symbol("ETHUSDT") == ["BTCUSDT", "ETHUSDT"]
    upsert_market_price({
        "symbol": "BTCUSDT", "price": 100.5,
        "event_time": "2026-01-01T00:00:00+00:00",
        "event_time_ms": 1767225600000,
    })
    assert list_market_prices()[0]["price"] == 100.5
    assert remove_watchlist_symbol("BTCUSDT") == ["ETHUSDT"]
    assert list_watchlist() == ["ETHUSDT"]


def test_stale_price_event_does_not_overwrite_newer_tick(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_STATE_DB", str(tmp_path / "market.sqlite3"))
    base = {
        "symbol": "BTCUSDT", "event_time": "2026-01-01T00:00:00+00:00",
    }
    upsert_market_price({**base, "price": 101, "event_time_ms": 200})
    upsert_market_price({**base, "price": 99, "event_time_ms": 100})
    assert list_market_prices()[0]["price"] == 101


def test_live_monitor_restores_watchlist_after_reconstruction(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_STATE_DB", str(tmp_path / "monitor.sqlite3"))
    from app.live_price_monitor import LivePriceMonitor
    first = LivePriceMonitor()
    first.add_symbol("ETHUSDT")
    second = LivePriceMonitor()
    assert second.watchlist_status()["symbols"] == ["ETHUSDT"]
