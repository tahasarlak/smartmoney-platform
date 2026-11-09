import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import forex_reference as fx


def test_symbol_catalog_contains_seven_majors_and_gold():
    assert set(fx.SYMBOLS) == {
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
        "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD",
    }


def test_inverts_usd_base_rate_for_eurusd():
    rows = [{"date": "2026-11-06", "base": "USD", "quote": "EUR", "rate": 0.92}]
    result = fx._normalise_rows(rows, "EURUSD", True)
    assert result[0]["rate"] == pytest.approx(1 / 0.92)


def test_keeps_usdjpy_direct():
    rows = [{"date": "2026-11-06", "base": "USD", "quote": "JPY", "rate": 153.25}]
    result = fx._normalise_rows(rows, "USDJPY", False)
    assert result[0]["rate"] == pytest.approx(153.25)


def test_skips_invalid_or_non_positive_rows():
    rows = [
        {"date": "bad-date", "rate": 1.2},
        {"date": "2026-11-06", "rate": 0},
        {"date": "2026-11-06", "rate": 1.1},
    ]
    result = fx._normalise_rows(rows, "EURUSD", False)
    assert len(result) == 1
    assert result[0]["rate"] == 1.1


def test_latest_result_never_claims_intraday_or_tradability(monkeypatch):
    async def fake_cached(key, params):
        if key == "usd-majors":
            return [
                {"date": "2026-11-06", "base": "USD", "quote": q, "rate": r}
                for q, r in {"EUR": .92, "GBP": .80, "JPY": 153, "CHF": .80,
                            "AUD": 1.52, "CAD": 1.40, "NZD": 1.75}.items()
            ]
        return [{"date": "2026-11-06", "base": "XAU", "quote": "USD", "rate": 3980.0}]

    monkeypatch.setattr(fx, "_get_latest_cached", fake_cached)
    import asyncio
    result = asyncio.run(fx.get_latest_reference_rates())
    assert result["available_symbols"] == 8
    assert result["intraday_available"] is False
    assert result["ohlc_available"] is False
    assert result["tradable"] is False
    assert result["execution_allowed"] is False
    assert next(x for x in result["items"] if x["symbol"] == "XAUUSD")["rate"] == 3980.0


def test_latest_handles_missing_xau_without_fabricating_price(monkeypatch):
    async def fake_cached(key, params):
        if key == "usd-majors":
            return [{"date": "2026-11-06", "base": "USD", "quote": "JPY", "rate": 153}]
        return []

    monkeypatch.setattr(fx, "_get_latest_cached", fake_cached)
    import asyncio
    result = asyncio.run(fx.get_latest_reference_rates())
    gold = next(x for x in result["items"] if x["symbol"] == "XAUUSD")
    assert gold["rate"] is None
    assert gold["status"] == "unavailable"


def test_router_exposes_reference_endpoints():
    app = FastAPI()
    app.include_router(fx.router)
    client = TestClient(app)
    response = client.get("/api/v1/forex/symbols")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 8


def test_history_rejects_unknown_symbol():
    app = FastAPI()
    app.include_router(fx.router)
    client = TestClient(app)
    response = client.get("/api/v1/forex/history/FAKE")
    assert response.status_code == 422


def test_history_rejects_reversed_date_range():
    app = FastAPI()
    app.include_router(fx.router)
    client = TestClient(app)
    response = client.get("/api/v1/forex/history/EURUSD?from=2026-11-10&to=2026-11-01")
    assert response.status_code == 422
