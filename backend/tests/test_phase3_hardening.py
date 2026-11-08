from __future__ import annotations

from fastapi import HTTPException

from app import main
from app.live_price_monitor import LivePriceMonitor, apply_trade_event


def test_monitor_status_and_snapshot_use_local_cache_without_database(monkeypatch):
    monitor = LivePriceMonitor()
    monitor._prices = {
        "BTCUSDT": {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "event_time": "2026-11-08T12:00:00+00:00",
            "event_time_ms": 1794148800000,
            "updated_at": "2026-11-08T12:00:00+00:00",
        }
    }

    def database_must_not_be_called():
        raise AssertionError("status/snapshot must not perform database I/O")

    monkeypatch.setattr("app.live_price_monitor.list_market_prices", database_must_not_be_called)

    assert monitor.status()["cached_prices"] == 1
    snapshot = monitor.market_snapshot()
    assert snapshot["count"] == 1
    assert snapshot["prices"][0]["symbol"] == "BTCUSDT"


def test_apply_trade_event_counts_only_actual_signal_changes(monkeypatch):
    signal = {
        "id": "signal-1",
        "status": "OPEN",
        "last_price": 100.0,
        "last_price_at": "2026-11-08T12:00:00+00:00",
    }

    def fake_list_signals(status=None, symbol=None, limit=500, include_private=False):
        return [signal] if status == "OPEN" else []

    def fake_update(signal_id, price, timestamp, include_private=False):
        return {
            **signal,
            "status": "TP1_HIT",
            "last_price": price,
            "last_price_at": timestamp,
        }

    monkeypatch.setattr("app.live_price_monitor.list_signals", fake_list_signals)
    monkeypatch.setattr("app.live_price_monitor.update_signal_price", fake_update)

    changed = apply_trade_event({
        "symbol": "BTCUSDT",
        "price": 102.0,
        "event_time": "2026-11-08T12:00:01+00:00",
    })

    assert changed == 1



def test_readiness_checks_database_and_returns_ready(monkeypatch):
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            assert str(statement) == "SELECT 1"

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(main, "get_engine", lambda: FakeEngine())

    assert main.readiness()["status"] == "ready"
    assert main.health()["status"] == "ok"


def test_readiness_returns_503_when_database_is_unavailable(monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise OSError("database unavailable")

    monkeypatch.setattr(main, "get_engine", lambda: BrokenEngine())

    try:
        main.readiness()
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("readiness must fail closed when PostgreSQL is unavailable")


def test_watchlist_cache_changes_only_after_successful_database_write(monkeypatch):
    monitor = LivePriceMonitor()
    monitor._initialized = True
    monitor._watchlist = {"ETHUSDT"}

    def fail_add(symbol):
        raise OSError("database unavailable")

    monkeypatch.setattr("app.live_price_monitor.add_watchlist_symbol", fail_add)

    try:
        monitor.add_symbol("BTCUSDT")
    except OSError:
        pass
    else:
        raise AssertionError("database write failure should propagate")

    assert monitor._watchlist == {"ETHUSDT"}
