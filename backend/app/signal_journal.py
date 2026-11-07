from __future__ import annotations
import json
import math
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "trade_journal.sqlite3"

def _db_path() -> Path:
    raw = os.getenv("TRADE_JOURNAL_DB")
    path = Path(raw).expanduser() if raw else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def _connect():
    con = sqlite3.connect(_db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    with _connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
          id TEXT PRIMARY KEY,
          symbol TEXT NOT NULL,
          direction TEXT NOT NULL CHECK(direction IN ('bullish','bearish')),
          status TEXT NOT NULL,
          setup_class TEXT,
          quality_score INTEGER,
          entry REAL NOT NULL,
          stop_loss REAL NOT NULL,
          tp1 REAL NOT NULL,
          tp2 REAL NOT NULL,
          tp3 REAL NOT NULL,
          zone_low REAL,
          zone_high REAL,
          min_rr REAL,
          risk_percent REAL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_price REAL,
          last_price_at TEXT,
          closed_at TEXT,
          close_reason TEXT,
          source TEXT NOT NULL DEFAULT 'research'
        );
        CREATE INDEX IF NOT EXISTS idx_signals_status_created
          ON signals(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_signals_symbol_created
          ON signals(symbol, created_at DESC);
        CREATE TABLE IF NOT EXISTS signal_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          signal_id TEXT NOT NULL REFERENCES signals(id),
          event_type TEXT NOT NULL,
          old_status TEXT,
          new_status TEXT,
          price REAL,
          note TEXT,
          created_at TEXT NOT NULL
        );
        """)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _row(row):
    if row is None: return None
    item=dict(row)
    item["take_profits"]=[
        {"name":"TP1","price":item.pop("tp1")},
        {"name":"TP2","price":item.pop("tp2")},
        {"name":"TP3","price":item.pop("tp3")},
    ]
    return item

def create_signal(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("status") not in ("pending_retest","zone_active"):
        raise ValueError("Only a valid pending_retest or zone_active plan can be journaled")
    if plan.get("execution_allowed") is not False:
        raise ValueError("Research signal must not enable execution")
    direction=plan.get("direction")
    entry=float(plan["entry"]); stop=float(plan["stop_loss"])
    targets=plan.get("take_profits") or []
    if direction not in ("bullish","bearish") or len(targets)<3:
        raise ValueError("Incomplete trade plan")
    tp=[float(x["price"]) for x in targets[:3]]
    if direction=="bullish" and not stop < entry < tp[0] < tp[1] < tp[2]:
        raise ValueError("Invalid bullish price ordering")
    if direction=="bearish" and not stop > entry > tp[0] > tp[1] > tp[2]:
        raise ValueError("Invalid bearish price ordering")
    now=_now(); sid=str(uuid.uuid4())
    zone=plan.get("zone") or {}
    with _connect() as con:
        con.execute("""INSERT INTO signals
        (id,symbol,direction,status,setup_class,quality_score,entry,stop_loss,tp1,tp2,tp3,
         zone_low,zone_high,min_rr,risk_percent,created_at,updated_at,last_price,source)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid,plan["symbol"],direction,"WAITING_ENTRY",plan.get("setup_class"),
         int(plan.get("quality_score",0)),entry,stop,*tp,zone.get("low"),zone.get("high"),
         plan.get("minimum_rr_requested"),plan.get("risk_percent_setting"),now,now,
         plan.get("current_price"),"research"))
        con.execute("""INSERT INTO signal_events
        (signal_id,event_type,new_status,price,note,created_at)
        VALUES (?,?,?,?,?,?)""",
        (sid,"SIGNAL_CREATED","WAITING_ENTRY",plan.get("current_price"),
         "Research-only plan saved; no broker order sent.",now))
        row=con.execute("SELECT * FROM signals WHERE id=?",(sid,)).fetchone()
    return _row(row)

def get_signal(signal_id: str):
    with _connect() as con:
        return _row(con.execute("SELECT * FROM signals WHERE id=?",(signal_id,)).fetchone())

def list_signals(status: str | None=None, symbol: str | None=None, limit: int=100):
    clauses=[]; args=[]
    if status:
        clauses.append("status=?"); args.append(status.upper())
    if symbol:
        clauses.append("symbol=?"); args.append(symbol.upper())
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    with _connect() as con:
        rows=con.execute("SELECT * FROM signals"+where+" ORDER BY created_at DESC LIMIT ?",
                         (*args,limit)).fetchall()
    return [_row(r) for r in rows]

def signal_events(signal_id: str):
    with _connect() as con:
        if not con.execute("SELECT 1 FROM signals WHERE id=?",(signal_id,)).fetchone():
            return None
        rows=con.execute("SELECT * FROM signal_events WHERE signal_id=? ORDER BY id",
                         (signal_id,)).fetchall()
    return [dict(r) for r in rows]

def update_signal_price(signal_id: str, price: float, timestamp: str | None=None):
    price = float(price)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Price must be a finite positive number")
    now=timestamp or _now()
    with _connect() as con:
        row=con.execute("SELECT * FROM signals WHERE id=?",(signal_id,)).fetchone()
        if row is None: return None
        old=row["status"]; new=old; reason=None
        if old in ("WAITING_ENTRY","OPEN","TP1_HIT","TP2_HIT"):
            direction=row["direction"]
            entered = (
                (price <= row["entry"]) if direction == "bullish"
                else (price >= row["entry"])
            )
            if old == "WAITING_ENTRY" and entered:
                new = "OPEN"
                reason = "Entry level reached by supplied price update"

            # Evaluate the furthest reached target on this tick. Trade feeds can
            # gap across multiple levels between messages, so do not require a
            # separate tick at every TP. Stop-loss has priority if the same
            # observed price is already beyond the stop.
            if new != "WAITING_ENTRY":
                if direction == "bullish":
                    stopped = price <= row["stop_loss"]
                    hit3 = price >= row["tp3"]
                    hit2 = price >= row["tp2"]
                    hit1 = price >= row["tp1"]
                else:
                    stopped = price >= row["stop_loss"]
                    hit3 = price <= row["tp3"]
                    hit2 = price <= row["tp2"]
                    hit1 = price <= row["tp1"]

                if stopped:
                    new = "STOPPED"
                    reason = "Stop-loss level reached"
                elif hit3:
                    new = "TP3_HIT"
                    reason = "Third target reached"
                elif hit2 and old in ("OPEN", "TP1_HIT", "TP2_HIT"):
                    new = "TP2_HIT"
                    reason = "Second target reached"
                elif hit1 and old in ("OPEN", "TP1_HIT"):
                    new = "TP1_HIT"
                    reason = "First target reached"
        closed_at=now if new in ("STOPPED","TP3_HIT") else row["closed_at"]
        con.execute("""UPDATE signals SET status=?,updated_at=?,last_price=?,last_price_at=?,
                       closed_at=?,close_reason=? WHERE id=?""",
                    (new,now,price,now,closed_at,reason,signal_id))
        if new != old:
            con.execute("""INSERT INTO signal_events
            (signal_id,event_type,old_status,new_status,price,note,created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (signal_id,"STATUS_CHANGED",old,new,price,reason,now))
        updated=con.execute("SELECT * FROM signals WHERE id=?",(signal_id,)).fetchone()
    return _row(updated)



def closed_signal_outcomes(limit: int = 5000) -> list[dict[str, Any]]:
    """Return only terminal journal outcomes; TP1/TP2 are not counted as wins."""
    if not 1 <= limit <= 20000:
        raise ValueError("limit must be 1..20000")
    with _connect() as con:
        rows = con.execute(
            "SELECT id,symbol,quality_score,status,closed_at,close_reason "
            "FROM signals WHERE status IN ('TP3_HIT','STOPPED') "
            "AND closed_at IS NOT NULL ORDER BY closed_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{
        "signal_id": row["id"],
        "symbol": row["symbol"],
        "quality_score": int(row["quality_score"] or 0),
        "won": row["status"] == "TP3_HIT",
        "closed_at": row["closed_at"],
        "status": row["status"],
    } for row in rows]
