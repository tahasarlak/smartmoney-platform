"""Free daily FX/metals reference rates from Frankfurter.

This is reference data, not executable broker quotes. The provider publishes
mostly daily mid-market observations; no OHLC candles are fabricated from a
single rate. Consequently this module must not feed the intraday SMC engine or
live order execution.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/forex", tags=["forex-reference"])
_BASE_URL = "https://api.frankfurter.dev/v2"
_CACHE_TTL = 900
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = asyncio.Lock()

# For USD-quoted majors, Frankfurter's USD base observation is inverted.
# For USDJPY/USDCHF/USDCAD the USD base observation is already the pair rate.
SYMBOLS: dict[str, dict[str, str]] = {
    "EURUSD": {"base": "USD", "quote": "EUR", "display": "EUR / USD", "name": "یورو / دلار آمریکا", "invert": "true"},
    "GBPUSD": {"base": "USD", "quote": "GBP", "display": "GBP / USD", "name": "پوند / دلار آمریکا", "invert": "true"},
    "USDJPY": {"base": "USD", "quote": "JPY", "display": "USD / JPY", "name": "دلار / ین ژاپن", "invert": "false"},
    "USDCHF": {"base": "USD", "quote": "CHF", "display": "USD / CHF", "name": "دلار / فرانک سوئیس", "invert": "false"},
    "AUDUSD": {"base": "USD", "quote": "AUD", "display": "AUD / USD", "name": "دلار استرالیا / دلار آمریکا", "invert": "true"},
    "USDCAD": {"base": "USD", "quote": "CAD", "display": "USD / CAD", "name": "دلار / دلار کانادا", "invert": "false"},
    "NZDUSD": {"base": "USD", "quote": "NZD", "display": "NZD / USD", "name": "دلار نیوزیلند / دلار آمریکا", "invert": "true"},
    "XAUUSD": {"base": "XAU", "quote": "USD", "display": "XAU / USD", "name": "طلا / دلار آمریکا", "invert": "false"},
}


class ForexReferenceProviderError(RuntimeError):
    pass


async def _fetch_rates(params: dict[str, str]) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12.0),
        headers={"Accept": "application/json", "User-Agent": "TRADF/1.0 (daily reference rates)"},
    ) as client:
        response = await client.get(f"{_BASE_URL}/rates", params=params)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        raise ForexReferenceProviderError("Frankfurter returned an unexpected response")
    return payload


def _normalise_rows(rows: list[dict[str, Any]], symbol: str, invert: bool) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            raw = float(row["rate"])
            observed = date.fromisoformat(str(row["date"]))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if raw <= 0:
            continue
        result.append({
            "date": observed.isoformat(),
            "rate": (1.0 / raw) if invert else raw,
            "symbol": symbol,
        })
    result.sort(key=lambda item: item["date"])
    return result


async def _get_latest_cached(key: str, params: dict[str, str]) -> list[dict[str, Any]]:
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    async with _cache_lock:
        now = time.monotonic()
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
        rows = await _fetch_rates(params)
        _cache[key] = (time.monotonic(), rows)
        return rows


async def get_latest_reference_rates() -> dict[str, Any]:
    currencies_task = _get_latest_cached(
        "usd-majors",
        {"base": "USD", "quotes": "EUR,GBP,JPY,CHF,AUD,CAD,NZD"},
    )
    gold_task = _get_latest_cached("xau-usd", {"base": "XAU", "quotes": "USD"})
    currency_rows, gold_rows = await asyncio.gather(currencies_task, gold_task, return_exceptions=True)

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    if isinstance(currency_rows, Exception):
        errors.append(f"FX: {currency_rows}")
        currency_rows = []
    if isinstance(gold_rows, Exception):
        errors.append(f"XAU: {gold_rows}")
        gold_rows = []

    for symbol, meta in SYMBOLS.items():
        if symbol == "XAUUSD":
            rows = _normalise_rows(gold_rows, symbol, False)
        else:
            rows = _normalise_rows(currency_rows, symbol, meta["invert"] == "true")
        if rows:
            latest = rows[-1]
            items.append({
                **latest,
                "display": meta["display"],
                "name": meta["name"],
                "frequency": "daily_reference",
                "tradable_quote": False,
                "source": "Frankfurter blended reference rates",
            })
        else:
            items.append({
                "symbol": symbol,
                "display": meta["display"],
                "name": meta["name"],
                "rate": None,
                "date": None,
                "frequency": "daily_reference",
                "tradable_quote": False,
                "source": "Frankfurter blended reference rates",
                "status": "unavailable",
            })

    available = sum(1 for item in items if item.get("rate") is not None)
    return {
        "provider": "Frankfurter",
        "provider_url": "https://frankfurter.dev/",
        "attribution": "Daily reference rates provided by Frankfurter (https://frankfurter.dev/).",
        "data_type": "daily_mid_market_reference",
        "frequency": "daily",
        "intraday_available": False,
        "ohlc_available": False,
        "tradable": False,
        "execution_allowed": False,
        "available_symbols": available,
        "symbol_count": len(SYMBOLS),
        "items": items,
        "warnings": [
            "These are daily reference/mid-market rates, not broker bid/ask quotes.",
            "No intraday candles are provided; do not use this feed for 1m/5m/15m SMC entries or live execution.",
            "Weekend and public-holiday observations may retain the last published business date; always inspect each item's date.",
        ] + errors,
    }


@router.get("/symbols")
def forex_reference_symbols():
    return {
        "provider": "Frankfurter",
        "frequency": "daily",
        "intraday_available": False,
        "tradable": False,
        "items": [
            {"symbol": symbol, "display": meta["display"], "name": meta["name"]}
            for symbol, meta in SYMBOLS.items()
        ],
    }


@router.get("/reference")
async def forex_reference_latest():
    try:
        return await get_latest_reference_rates()
    except (httpx.HTTPError, ForexReferenceProviderError) as exc:
        raise HTTPException(status_code=502, detail=f"Forex reference provider unavailable: {exc}") from exc


@router.get("/history/{symbol}")
async def forex_reference_history(
    symbol: str,
    from_date: date = Query(default_factory=lambda: date.today() - timedelta(days=90), alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
):
    symbol = symbol.strip().upper()
    meta = SYMBOLS.get(symbol)
    if not meta:
        raise HTTPException(status_code=422, detail="Unsupported forex reference symbol")
    if from_date > to_date:
        raise HTTPException(status_code=422, detail="from must be on or before to")
    if (to_date - from_date).days > 3650:
        raise HTTPException(status_code=422, detail="History range cannot exceed 10 years")

    try:
        rows = await _fetch_rates({
            "base": meta["base"],
            "quotes": meta["quote"],
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        })
    except (httpx.HTTPError, ForexReferenceProviderError) as exc:
        raise HTTPException(status_code=502, detail=f"Forex reference provider unavailable: {exc}") from exc

    observations = _normalise_rows(rows, symbol, meta["invert"] == "true")
    return {
        "symbol": symbol,
        "provider": "Frankfurter",
        "frequency": "daily",
        "data_type": "daily_reference_observations",
        "ohlc_available": False,
        "tradable": False,
        "observations": observations,
        "count": len(observations),
        "attribution": "https://frankfurter.dev/",
        "warning": "Reference observations are not OHLC candles and must not be passed to the SMC candle engine.",
    }
