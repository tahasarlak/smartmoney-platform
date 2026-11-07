from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "market_state.sqlite3"


def _db_path() -> Path:
    raw = os.getenv("MARKET_STATE_DB")
    path = Path(raw).expanduser() if raw else _DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_market_store() -> None:
    with _connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS market_prices (
            symbol TEXT PRIMARY KEY,
            price REAL NOT NULL,
            event_time TEXT NOT NULL,
            event_time_ms INTEGER NOT NULL,
            provider TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS market_watchlist (
            symbol TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'binance_spot',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_market_prices_updated
            ON market_prices(updated_at DESC);
        """)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_watchlist_symbol(symbol: str, provider: str = "binance_spot") -> list[str]:
    symbol = str(symbol).strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    init_market_store()
    with _connect() as con:
        con.execute(
            "INSERT INTO market_watchlist(symbol,provider,created_at) VALUES(?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET provider=excluded.provider",
            (symbol, provider, _now()),
        )
    return list_watchlist()


def remove_watchlist_symbol(symbol: str) -> list[str]:
    symbol = str(symbol).strip().upper()
    init_market_store()
    with _connect() as con:
        con.execute("DELETE FROM market_watchlist WHERE symbol=?", (symbol,))
    return list_watchlist()


def list_watchlist() -> list[str]:
    init_market_store()
    with _connect() as con:
        rows = con.execute("SELECT symbol FROM market_watchlist ORDER BY symbol").fetchall()
    return [row["symbol"] for row in rows]


def upsert_market_price(event: dict[str, Any], provider: str = "binance_spot") -> None:
    init_market_store()
    symbol = str(event["symbol"]).upper()
    price = float(event["price"])
    event_time = str(event["event_time"])
    event_time_ms = int(event["event_time_ms"])
    if price <= 0:
        raise ValueError("price must be positive")
    with _connect() as con:
        con.execute("""
            INSERT INTO market_prices(symbol,price,event_time,event_time_ms,provider,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                price=excluded.price,
                event_time=excluded.event_time,
                event_time_ms=excluded.event_time_ms,
                provider=excluded.provider,
                updated_at=excluded.updated_at
            WHERE excluded.event_time_ms >= market_prices.event_time_ms
        """, (symbol, price, event_time, event_time_ms, provider, _now()))


def list_market_prices() -> list[dict[str, Any]]:
    init_market_store()
    with _connect() as con:
        rows = con.execute(
            "SELECT symbol,price,event_time,event_time_ms,provider,updated_at "
            "FROM market_prices ORDER BY symbol"
        ).fetchall()
    return [dict(row) for row in rows]
