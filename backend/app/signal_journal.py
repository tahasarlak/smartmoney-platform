"""Signal journal backed by Neon PostgreSQL.

Public signals have visibility='public' and user_id=NULL. Private signals
require an authenticated owner. Existing callers remain compatible and
create public research signals unless user_id/visibility are supplied.
"""
from __future__ import annotations
import math, uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, and_, or_
from .database import session_scope, get_session_factory
from .db_models import Signal, SignalEvent

def init_db() -> None:
    """Compatibility no-op. Alembic owns schema creation."""
    return None

def _now(): return datetime.now(timezone.utc)


def _parse_timestamp(value: str | datetime) -> datetime:
    """Parse an ISO timestamp and normalize it to UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row(row):
    if row is None: return None
    item = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    item["take_profits"] = [
        {"name": "TP1", "price": item.pop("tp1")},
        {"name": "TP2", "price": item.pop("tp2")},
        {"name": "TP3", "price": item.pop("tp3")},
    ]
    for key in ("created_at", "updated_at"):
        if item.get(key): item[key] = item[key].isoformat()
    return item

def create_signal(plan: dict[str, Any], user_id: str | None = None,
                  visibility: str = "public") -> dict[str, Any]:
    if plan.get("status") not in ("pending_retest", "zone_active"):
        raise ValueError("Only a valid pending_retest or zone_active plan can be journaled")
    if plan.get("execution_allowed") is not False:
        raise ValueError("Research signal must not enable execution")
    if visibility not in ("public", "private"):
        raise ValueError("visibility must be public or private")
    if visibility == "private" and not user_id:
        raise ValueError("Private signals require an authenticated user_id")
    if visibility == "public": user_id = None
    direction = plan.get("direction")
    entry, stop = float(plan["entry"]), float(plan["stop_loss"])
    targets = plan.get("take_profits") or []
    if direction not in ("bullish", "bearish") or len(targets) < 3:
        raise ValueError("Incomplete trade plan")
    tp = [float(x["price"]) for x in targets[:3]]
    if direction == "bullish" and not stop < entry < tp[0] < tp[1] < tp[2]:
        raise ValueError("Invalid bullish price ordering")
    if direction == "bearish" and not stop > entry > tp[0] > tp[1] > tp[2]:
        raise ValueError("Invalid bearish price ordering")
    now, sid, zone = _now(), str(uuid.uuid4()), plan.get("zone") or {}
    with session_scope() as db:
        row = Signal(id=sid, user_id=user_id, visibility=visibility,
            symbol=str(plan["symbol"]).upper(), direction=direction,
            status="WAITING_ENTRY", setup_class=plan.get("setup_class"),
            quality_score=int(plan.get("quality_score", 0)), entry=entry,
            stop_loss=stop, tp1=tp[0], tp2=tp[1], tp3=tp[2],
            zone_low=zone.get("low"), zone_high=zone.get("high"),
            min_rr=plan.get("minimum_rr_requested"),
            risk_percent=plan.get("risk_percent_setting"), created_at=now,
            updated_at=now, last_price=plan.get("current_price"), source="research")
        db.add(row)
        db.add(SignalEvent(signal_id=sid, event_type="SIGNAL_CREATED",
            new_status="WAITING_ENTRY", price=plan.get("current_price"),
            note="Research-only plan saved; no broker order sent.", created_at=now))
        db.flush()
        return _row(row)

def _visibility_filter(user_id: str | None):
    if user_id:
        return or_(Signal.visibility == "public",
                   and_(Signal.visibility == "private", Signal.user_id == user_id))
    return Signal.visibility == "public"

def get_signal(signal_id: str, user_id: str | None = None):
    with get_session_factory()() as db:
        row = db.scalar(select(Signal).where(Signal.id == signal_id, _visibility_filter(user_id)))
        return _row(row)

def list_signals(status: str | None = None, symbol: str | None = None,
                 limit: int = 100, user_id: str | None = None,
                 include_private: bool = False):
    if not 1 <= int(limit) <= 500: raise ValueError("limit must be 1..500")
    # include_private is reserved for trusted internal services (e.g. the
    # market monitor), never expose it directly as an unauthenticated API flag.
    visibility_clause = None if include_private else _visibility_filter(user_id)
    stmt = select(Signal)
    if visibility_clause is not None:
        stmt = stmt.where(visibility_clause)
    if status: stmt = stmt.where(Signal.status == status.upper())
    if symbol: stmt = stmt.where(Signal.symbol == symbol.upper())
    stmt = stmt.order_by(Signal.created_at.desc()).limit(int(limit))
    with get_session_factory()() as db:
        return [_row(r) for r in db.scalars(stmt).all()]

def signal_events(signal_id: str, user_id: str | None = None):
    with get_session_factory()() as db:
        exists = db.scalar(select(Signal.id).where(Signal.id == signal_id, _visibility_filter(user_id)))
        if not exists: return None
        rows = db.scalars(select(SignalEvent).where(SignalEvent.signal_id == signal_id).order_by(SignalEvent.id)).all()
        return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows]

def update_signal_price(signal_id: str, price: float, timestamp: str | None = None,
                        user_id: str | None = None, include_private: bool = False):
    price = float(price)
    if not math.isfinite(price) or price <= 0: raise ValueError("Price must be a finite positive number")
    incoming_time = _parse_timestamp(timestamp) if timestamp else _now()
    now_text = incoming_time.isoformat()
    with session_scope() as db:
        stmt = select(Signal).where(Signal.id == signal_id)
        if not include_private:
            stmt = stmt.where(_visibility_filter(user_id))
        row = db.scalar(stmt.with_for_update())
        if row is None: return None

        # Terminal signals are immutable: a later manual or delayed price
        # update cannot reopen or otherwise rewrite a closed outcome.
        if row.status not in ("WAITING_ENTRY", "OPEN", "TP1_HIT", "TP2_HIT"):
            return _row(row)

        # A delayed/out-of-order market tick must never overwrite a newer price
        # or move a signal through its lifecycle using stale market data.
        if row.last_price_at:
            try:
                previous_time = _parse_timestamp(row.last_price_at)
            except (TypeError, ValueError):
                previous_time = None
            # Binance can emit multiple distinct trades within the same millisecond.
            # WebSocket delivery is ordered, so reject strictly older ticks while
            # allowing the next trade carrying the same millisecond timestamp.
            if previous_time is not None and incoming_time < previous_time:
                return _row(row)

        old, new, reason = row.status, row.status, None
        if old in ("WAITING_ENTRY", "OPEN", "TP1_HIT", "TP2_HIT"):
            entered = price <= row.entry if row.direction == "bullish" else price >= row.entry
            if old == "WAITING_ENTRY" and entered:
                new, reason = "OPEN", "Entry level reached by supplied price update"
            if new != "WAITING_ENTRY":
                if row.direction == "bullish":
                    stopped, hit3, hit2, hit1 = price <= row.stop_loss, price >= row.tp3, price >= row.tp2, price >= row.tp1
                else:
                    stopped, hit3, hit2, hit1 = price >= row.stop_loss, price <= row.tp3, price <= row.tp2, price <= row.tp1
                if stopped: new, reason = "STOPPED", "Stop-loss level reached"
                elif hit3: new, reason = "TP3_HIT", "Third target reached"
                elif hit2 and old in ("OPEN", "TP1_HIT", "TP2_HIT"): new, reason = "TP2_HIT", "Second target reached"
                elif hit1 and old in ("OPEN", "TP1_HIT"): new, reason = "TP1_HIT", "First target reached"
        row.status, row.updated_at, row.last_price, row.last_price_at = new, _now(), price, now_text
        if new in ("STOPPED", "TP3_HIT"): row.closed_at, row.close_reason = now_text, reason
        if new != old:
            db.add(SignalEvent(signal_id=signal_id, event_type="STATUS_CHANGED",
                old_status=old, new_status=new, price=price, note=reason, created_at=_now()))
        db.flush()
        return _row(row)

def closed_signal_outcomes(limit: int = 5000) -> list[dict[str, Any]]:
    if not 1 <= limit <= 20000: raise ValueError("limit must be 1..20000")
    with get_session_factory()() as db:
        rows = db.execute(select(Signal.id, Signal.symbol, Signal.quality_score,
            Signal.status, Signal.closed_at, Signal.close_reason)
            .where(
                Signal.visibility == "public",
                Signal.status.in_(("TP3_HIT", "STOPPED")),
                Signal.closed_at.is_not(None),
            )
            .order_by(Signal.closed_at.asc()).limit(limit)).all()
    return [{"signal_id": r.id, "symbol": r.symbol, "quality_score": int(r.quality_score or 0),
             "won": r.status == "TP3_HIT", "closed_at": r.closed_at, "status": r.status} for r in rows]
