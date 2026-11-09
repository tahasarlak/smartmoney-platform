from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.mt5_market_data import (
    SUPPORTED_SYMBOLS, CandleIn, SeriesIn, BatchIn,
    _require_bridge_token, _upsert_candles, _save_heartbeat,
)
from app.production_models import MT5MarketCandle, MT5BridgeHeartbeat


def _candle(t=1, o=1.1, h=1.2, low=1.0, c=1.15):
    return {"time": t, "open": o, "high": h, "low": low, "close": c, "volume": 10, "spread_points": 2}


def test_supported_universe_is_seven_fx_pairs_and_gold():
    assert SUPPORTED_SYMBOLS == (
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
        "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD",
    )


def test_candle_rejects_inconsistent_ohlc():
    with pytest.raises(ValidationError):
        CandleIn(**_candle(h=1.05))


def test_candle_rejects_non_finite_values():
    with pytest.raises(ValidationError):
        CandleIn(**_candle(o=float("nan")))


def test_series_rejects_unknown_symbol():
    with pytest.raises(ValidationError):
        SeriesIn(symbol="EURGBP", broker_symbol="EURGBP", timeframe="5m", candles=[_candle()])


def test_series_requires_strictly_increasing_timestamps():
    with pytest.raises(ValidationError):
        SeriesIn(symbol="EURUSD", broker_symbol="EURUSD.a", timeframe="5m",
                 candles=[_candle(2), _candle(2)])


def test_batch_is_demo_only_and_rejects_duplicate_series():
    series = SeriesIn(symbol="EURUSD", broker_symbol="EURUSD", timeframe="5m", candles=[_candle()])
    with pytest.raises(ValidationError):
        BatchIn(bridge_id="bridge-01", broker_server="Demo", terminal_version="1",
                account_mode="real", series=[series])
    with pytest.raises(ValidationError):
        BatchIn(bridge_id="bridge-01", broker_server="Demo", terminal_version="1",
                account_mode="demo", series=[series, series])


def test_bridge_token_fails_closed_and_compares_configured_secret(monkeypatch):
    monkeypatch.delenv("TRADF_MT5_BRIDGE_TOKEN", raising=False)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _require_bridge_token("anything")
    assert exc.value.status_code == 503

    monkeypatch.setenv("TRADF_MT5_BRIDGE_TOKEN", "x" * 48)
    with pytest.raises(HTTPException) as exc:
        _require_bridge_token("wrong")
    assert exc.value.status_code == 401
    _require_bridge_token("x" * 48)


def test_candle_upsert_updates_existing_record():
    engine = create_engine("sqlite:///:memory:")
    MT5MarketCandle.__table__.create(engine)
    now = datetime.now(timezone.utc)
    series = [SeriesIn(
        symbol="EURUSD", broker_symbol="EURUSD.a", timeframe="5m",
        candles=[_candle()],
    )]
    with Session(engine) as db:
        assert _upsert_candles(db, series, now) == 1
        db.commit()
        changed = [SeriesIn(
            symbol="EURUSD", broker_symbol="EURUSD.a", timeframe="5m",
            candles=[_candle(o=1.11, h=1.22, low=1.01, c=1.16)],
        )]
        assert _upsert_candles(db, changed, now) == 1
        db.commit()
        row = db.get(MT5MarketCandle, ("EURUSD", "5m", 1))
        assert row.open == pytest.approx(1.11)
        assert row.close == pytest.approx(1.16)
    engine.dispose()


def test_heartbeat_stores_demo_status_without_account_number():
    engine = create_engine("sqlite:///:memory:")
    MT5BridgeHeartbeat.__table__.create(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        _save_heartbeat(db, "bridge-01", "Broker-Demo", "5.0", now)
        db.commit()
        row = db.get(MT5BridgeHeartbeat, "bridge-01")
        assert row.account_mode == "demo"
        assert row.status == "connected"
        assert row.broker_server == "Broker-Demo"
    engine.dispose()
