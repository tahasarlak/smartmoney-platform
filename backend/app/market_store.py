"""Shared market prices and shared market watchlist backed by PostgreSQL."""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from .database import session_scope, get_session_factory
from .db_models import MarketPrice, MarketWatchlist

def init_market_store() -> None:
    """Compatibility no-op: schema is managed exclusively by Alembic."""
    return None

def _now():
    return datetime.now(timezone.utc)

def add_watchlist_symbol(symbol: str, provider: str = "binance_spot") -> list[str]:
    symbol = str(symbol).strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    with session_scope() as db:
        stmt = pg_insert(MarketWatchlist).values(symbol=symbol, provider=provider)
        stmt = stmt.on_conflict_do_update(index_elements=[MarketWatchlist.symbol],
                                          set_={"provider": stmt.excluded.provider})
        db.execute(stmt)
    return list_watchlist()

def remove_watchlist_symbol(symbol: str) -> list[str]:
    symbol = str(symbol).strip().upper()
    with session_scope() as db:
        row = db.get(MarketWatchlist, symbol)
        if row is not None:
            db.delete(row)
    return list_watchlist()

def list_watchlist() -> list[str]:
    with get_session_factory()() as db:
        return list(db.scalars(select(MarketWatchlist.symbol).order_by(MarketWatchlist.symbol)))

def upsert_market_price(event: dict[str, Any], provider: str = "binance_spot") -> None:
    symbol = str(event["symbol"]).strip().upper()
    price = float(event["price"])
    event_time = str(event["event_time"])
    event_time_ms = int(event["event_time_ms"])
    if not symbol or not math.isfinite(price) or price <= 0 or event_time_ms < 0:
        raise ValueError("symbol, finite positive price and non-negative event_time_ms are required")
    with session_scope() as db:
        stmt = pg_insert(MarketPrice).values(symbol=symbol, price=price,
            event_time=event_time, event_time_ms=event_time_ms,
            provider=provider, updated_at=_now())
        stmt = stmt.on_conflict_do_update(index_elements=[MarketPrice.symbol],
            set_={"price": stmt.excluded.price, "event_time": stmt.excluded.event_time,
                  "event_time_ms": stmt.excluded.event_time_ms,
                  "provider": stmt.excluded.provider, "updated_at": stmt.excluded.updated_at},
            where=stmt.excluded.event_time_ms >= MarketPrice.event_time_ms)
        db.execute(stmt)

def list_market_prices() -> list[dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.scalars(select(MarketPrice).order_by(MarketPrice.symbol)).all()
        return [{"symbol": r.symbol, "price": r.price, "event_time": r.event_time,
                 "event_time_ms": r.event_time_ms, "provider": r.provider,
                 "updated_at": r.updated_at.isoformat() if r.updated_at else None} for r in rows]
