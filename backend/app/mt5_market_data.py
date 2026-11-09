"""Read-only MetaTrader 5 demo market-data bridge.

The Windows bridge pushes OHLCV data outbound over HTTPS. This API never sends
orders to MetaTrader and fails closed when its shared bridge token is absent.
"""
from __future__ import annotations

import hmac
import math
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import get_session_factory
from .production_models import MT5MarketCandle, MT5BridgeHeartbeat
from .mtf import TIMEFRAMES, analyze_multi_timeframe

router = APIRouter(prefix="/api/v1/mt5", tags=["MetaTrader 5 Demo Market Data"])

SUPPORTED_SYMBOLS = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD",
)
SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")


class CandleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time: int = Field(gt=0)
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(default=0, ge=0)
    spread_points: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_ohlc(self):
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError("Candle values must be finite")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Candle high is inconsistent")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Candle low is inconsistent")
        return self


class SeriesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    broker_symbol: str = Field(min_length=1, max_length=40)
    timeframe: Literal["1m", "5m", "15m", "1h", "4h"]
    candles: list[CandleIn] = Field(min_length=1, max_length=10000)

    @field_validator("symbol")
    @classmethod
    def supported_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in SUPPORTED_SYMBOLS:
            raise ValueError("Unsupported MT5 symbol")
        return normalized

    @model_validator(mode="after")
    def ordered_unique_candles(self):
        times = [c.time for c in self.candles]
        if times != sorted(set(times)):
            raise ValueError("Candle timestamps must be strictly increasing")
        return self


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bridge_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    broker_server: str = Field(min_length=1, max_length=120)
    terminal_version: str = Field(min_length=1, max_length=80)
    account_mode: Literal["demo"]
    series: list[SeriesIn] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def bounded_batch(self):
        keys = [(x.symbol, x.timeframe) for x in self.series]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate symbol/timeframe series")
        total = sum(len(x.candles) for x in self.series)
        if total > 50000:
            raise ValueError("A batch may contain at most 50000 candles")
        return self


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bridge_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    broker_server: str = Field(min_length=1, max_length=120)
    terminal_version: str = Field(min_length=1, max_length=80)
    account_mode: Literal["demo"]


class AnalysisIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    limit: int = Field(default=300, ge=51, le=1000)
    min_rr: float = Field(default=2.0, ge=0.5, le=10)
    allow_counter_trend: bool = True

    @field_validator("symbol")
    @classmethod
    def supported_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in SUPPORTED_SYMBOLS:
            raise ValueError("Unsupported MT5 symbol")
        return normalized


def _require_bridge_token(token: str | None) -> None:
    expected = os.getenv("TRADF_MT5_BRIDGE_TOKEN", "").strip()
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="MT5 bridge authentication is not configured")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid MT5 bridge token")


def _db_session():
    return get_session_factory()()


def _upsert_candles(db, series: list[SeriesIn], now: datetime) -> int:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        insert_fn = pg_insert
    elif dialect == "sqlite":
        insert_fn = sqlite_insert
    else:
        raise RuntimeError("MT5 candle persistence supports PostgreSQL and SQLite only")

    rows = []
    for item in series:
        for candle in item.candles:
            rows.append({
                "symbol": item.symbol,
                "timeframe": item.timeframe,
                "candle_time": candle.time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "spread_points": candle.spread_points,
                "broker_symbol": item.broker_symbol,
                "received_at": now,
            })

    written = 0
    for start in range(0, len(rows), 500):
        chunk = rows[start:start + 500]
        statement = insert_fn(MT5MarketCandle).values(chunk)
        updates = {
            key: getattr(statement.excluded, key)
            for key in ("open", "high", "low", "close", "volume", "spread_points", "broker_symbol", "received_at")
        }
        statement = statement.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "candle_time"],
            set_=updates,
        )
        db.execute(statement)
        written += len(chunk)
    return written


def _save_heartbeat(db, bridge_id: str, broker_server: str, terminal_version: str, now: datetime):
    row = db.get(MT5BridgeHeartbeat, bridge_id)
    if row is None:
        row = MT5BridgeHeartbeat(
            bridge_id=bridge_id,
            broker_server=broker_server,
            terminal_version=terminal_version,
            account_mode="demo",
            last_seen_at=now,
            status="connected",
            last_error=None,
        )
        db.add(row)
    else:
        row.broker_server = broker_server
        row.terminal_version = terminal_version
        row.account_mode = "demo"
        row.last_seen_at = now
        row.status = "connected"
        row.last_error = None


@router.get("/market/symbols")
def mt5_symbols():
    db = _db_session()
    try:
        latest = db.execute(
            select(MT5MarketCandle.symbol, func.max(MT5MarketCandle.candle_time))
            .group_by(MT5MarketCandle.symbol)
        ).all()
        latest_map = {symbol: stamp for symbol, stamp in latest}
        now = datetime.now(timezone.utc).timestamp()
        return {
            "provider": "MetaTrader 5 broker demo feed",
            "execution_enabled": False,
            "symbols": [
                {
                    "symbol": symbol,
                    "available": symbol in latest_map,
                    "last_candle_time": latest_map.get(symbol),
                    "age_seconds": max(0, int(now - latest_map[symbol])) if symbol in latest_map else None,
                }
                for symbol in SUPPORTED_SYMBOLS
            ],
        }
    finally:
        db.close()


@router.get("/market/status")
def mt5_market_status():
    db = _db_session()
    try:
        heartbeat = db.scalar(
            select(MT5BridgeHeartbeat).order_by(MT5BridgeHeartbeat.last_seen_at.desc()).limit(1)
        )
        if heartbeat is None:
            return {"status": "offline", "connected": False, "demo_only": True, "execution_enabled": False}
        age = max(0, int((datetime.now(timezone.utc) - (
            heartbeat.last_seen_at.replace(tzinfo=timezone.utc)
            if heartbeat.last_seen_at.tzinfo is None else heartbeat.last_seen_at
        )).total_seconds()))
        connected = age <= 120 and heartbeat.status == "connected"
        return {
            "status": "connected" if connected else "stale",
            "connected": connected,
            "bridge_id": heartbeat.bridge_id,
            "last_seen_at": heartbeat.last_seen_at.isoformat(),
            "age_seconds": age,
            "demo_only": True,
            "execution_enabled": False,
        }
    finally:
        db.close()


@router.post("/bridge/heartbeat")
def mt5_bridge_heartbeat(
    payload: HeartbeatIn,
    bridge_token: str | None = Header(default=None, alias="X-TRADF-BRIDGE-TOKEN"),
):
    _require_bridge_token(bridge_token)
    db = _db_session()
    try:
        now = datetime.now(timezone.utc)
        _save_heartbeat(db, payload.bridge_id, payload.broker_server, payload.terminal_version, now)
        db.commit()
        return {"accepted": True, "bridge_id": payload.bridge_id, "account_mode": "demo"}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/bridge/candles")
def ingest_mt5_candles(
    payload: BatchIn,
    bridge_token: str | None = Header(default=None, alias="X-TRADF-BRIDGE-TOKEN"),
):
    _require_bridge_token(bridge_token)
    db = _db_session()
    try:
        now = datetime.now(timezone.utc)
        count = _upsert_candles(db, payload.series, now)
        _save_heartbeat(db, payload.bridge_id, payload.broker_server, payload.terminal_version, now)
        db.commit()
        return {
            "accepted": True,
            "series_count": len(payload.series),
            "candle_rows_upserted": count,
            "account_mode": "demo",
            "execution_enabled": False,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/market/klines")
def get_mt5_klines(
    symbol: str = Query(...),
    timeframe: Literal["1m", "5m", "15m", "1h", "4h"] = Query(...),
    limit: int = Query(default=300, ge=1, le=10000),
):
    normalized = symbol.strip().upper()
    if normalized not in SUPPORTED_SYMBOLS:
        raise HTTPException(status_code=422, detail="Unsupported MT5 symbol")
    db = _db_session()
    try:
        rows = db.scalars(
            select(MT5MarketCandle)
            .where(MT5MarketCandle.symbol == normalized, MT5MarketCandle.timeframe == timeframe)
            .order_by(MT5MarketCandle.candle_time.desc())
            .limit(limit)
        ).all()
        rows.reverse()
        return {
            "provider": "MetaTrader 5 broker demo feed",
            "symbol": normalized,
            "timeframe": timeframe,
            "candles": [{
                "time": row.candle_time,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "spread_points": row.spread_points,
            } for row in rows],
        }
    finally:
        db.close()


@router.post("/analysis/multi-timeframe")
def analyze_mt5_multi_timeframe(payload: AnalysisIn):
    db = _db_session()
    try:
        candles_by_tf = {}
        for timeframe in TIMEFRAMES:
            rows = db.scalars(
                select(MT5MarketCandle)
                .where(
                    MT5MarketCandle.symbol == payload.symbol,
                    MT5MarketCandle.timeframe == timeframe,
                )
                .order_by(MT5MarketCandle.candle_time.desc())
                .limit(payload.limit)
            ).all()
            rows.reverse()
            if len(rows) < 51:
                raise HTTPException(
                    status_code=409,
                    detail=f"Insufficient MT5 history for {payload.symbol} {timeframe}: {len(rows)} candles; at least 51 required",
                )
            candles_by_tf[timeframe] = [{
                "time": row.candle_time, "open": row.open, "high": row.high,
                "low": row.low, "close": row.close, "volume": row.volume,
            } for row in rows]
        result = analyze_multi_timeframe(
            payload.symbol, candles_by_tf,
            min_rr=payload.min_rr,
            allow_counter_trend=payload.allow_counter_trend,
        )
        return {"provider": "MetaTrader 5 broker demo feed", **result}
    finally:
        db.close()
