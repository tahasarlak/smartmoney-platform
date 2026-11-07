from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, field_validator

from .data_quality import validate_candle_series
from .scanner import TIMEFRAMES, scan_symbol

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
_INTERVAL_SECONDS = {
    "4h": 14_400,
    "1h": 3_600,
    "15m": 900,
    "5m": 300,
    "1m": 60,
}


class MultiSymbolScanRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=30)
    limit: int = Field(default=300, ge=100, le=1000)
    max_concurrency: int = Field(default=4, ge=1, le=6)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for raw in values:
            symbol = str(raw).strip().upper()
            if not _SYMBOL_RE.fullmatch(symbol):
                raise ValueError(f"Invalid symbol format: {raw}")
            if symbol not in seen:
                normalized.append(symbol)
                seen.add(symbol)
        if not normalized:
            raise ValueError("At least one unique symbol is required")
        return normalized


async def scan_many_symbols(
    symbols: list[str],
    limit: int,
    fetch_klines: Callable[[str, str, int], Awaitable[list[dict[str, Any]]]],
    analyze_smc_fn: Callable[..., dict[str, Any]],
    settings: dict[str, Any] | None = None,
    max_concurrency: int = 4,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    """Scan a bounded list of symbols; failures are isolated per symbol.

    No orders are placed. Only closed candles are analyzed by the existing SMC engine.
    """
    if not 1 <= len(symbols) <= 30:
        raise ValueError("symbols must contain between 1 and 30 entries")
    if not 100 <= limit <= 1000:
        raise ValueError("limit must be between 100 and 1000")
    if not 1 <= max_concurrency <= 6:
        raise ValueError("max_concurrency must be between 1 and 6")

    normalized = list(dict.fromkeys(str(s).strip().upper() for s in symbols))
    if any(not _SYMBOL_RE.fullmatch(s) for s in normalized):
        raise ValueError("One or more symbols have invalid format")

    semaphore = asyncio.Semaphore(max_concurrency)
    scan_time = int(now_epoch if now_epoch is not None else time.time())

    async def scan_one(symbol: str) -> dict[str, Any]:
        async with semaphore:
            try:
                fetched = await asyncio.gather(*[
                    fetch_klines(symbol, tf, limit) for tf in TIMEFRAMES
                ])
                candles_by_tf = dict(zip(TIMEFRAMES, fetched))

                checks = {}
                for tf in TIMEFRAMES:
                    check = validate_candle_series(
                        candles_by_tf[tf], tf, scan_time
                    )
                    checks[tf] = check
                    if not check["valid"]:
                        return {
                            "symbol": symbol,
                            "status": "data_rejected",
                            "reason": check["reason"],
                            "failed_timeframe": tf,
                            "data_quality": checks,
                        }

                analyses = {
                    tf: analyze_smc_fn(
                        symbol, candles_by_tf[tf], swing_length=3
                    )
                    for tf in TIMEFRAMES
                }
                result = scan_symbol(
                    symbol, candles_by_tf, analyses, settings=settings
                )
                return {
                    "symbol": symbol,
                    "status": "scanned",
                    "data_quality": checks,
                    **result,
                }
            except Exception as exc:
                return {
                    "symbol": symbol,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }

    results = await asyncio.gather(*(scan_one(s) for s in normalized))
    scanned = [x for x in results if x["status"] == "scanned"]
    errors = [x for x in results if x["status"] == "error"]
    rejected = [x for x in results if x["status"] == "data_rejected"]

    opportunities = []
    for item in scanned:
        for scenario in item.get("scenarios", []):
            if scenario.get("zone") and scenario.get("state") not in ("monitoring",):
                opportunities.append({
                    "symbol": item["symbol"],
                    "primary_bias": item.get("primary_bias"),
                    **scenario,
                })

    opportunities.sort(
        key=lambda x: (x.get("quality_score", 0), x.get("confirmation") == "confirmed_trigger"),
        reverse=True,
    )

    return {
        "provider": "Binance public market data",
        "engine_version": "multi-symbol-scanner-5.0",
        "requested_symbols": normalized,
        "summary": {
            "requested": len(normalized),
            "scanned": len(scanned),
            "data_rejected": len(rejected),
            "errors": len(errors),
            "opportunities": len(opportunities),
        },
        "opportunities": opportunities,
        "results": results,
        "estimated_win_probability": None,
        "execution_allowed": False,
        "note": "Watchlist research only. No trade orders are created or sent.",
    }
