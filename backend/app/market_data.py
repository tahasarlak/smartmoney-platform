"""Resilient public market-data access for Binance spot klines.

Uses Binance's public market-data endpoint first, falls back across official
Binance API hosts, applies a short in-process cache, and never hammers a host
after HTTP 418/429 responses.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

from .config import settings

_DEFAULT_HOSTS = (
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api.binance.com",
)
_CACHE_TTL_SECONDS = 15
_CACHE_MAX_ITEMS = 256
_cache: dict[tuple[str, str, int], tuple[float, list[dict[str, Any]]]] = {}
_cache_lock = asyncio.Lock()


class MarketDataProviderError(RuntimeError):
    """Raised when every configured public market-data host fails."""


def _hosts() -> list[str]:
    configured = str(settings.binance_base_url or "").strip().rstrip("/")
    candidates = [configured, *_DEFAULT_HOSTS]
    result: list[str] = []
    for host in candidates:
        if host and host not in result:
            result.append(host)
    return result


def _parse_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise MarketDataProviderError("Binance returned an unexpected klines payload")
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise MarketDataProviderError("Binance returned a malformed kline row")
        parsed.append({
            "time": int(row[0] // 1000),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })
    if not parsed:
        raise MarketDataProviderError("Binance returned no candles")
    return parsed


async def _request_host(host: str, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
    url = f"{host}/api/v3/klines"
    async with httpx.AsyncClient(
        timeout=12,
        headers={"User-Agent": "TRADF-MarketData/1.0", "Accept": "application/json"},
    ) as client:
        response = await client.get(
            url,
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
    if response.status_code in (418, 429):
        retry_after = response.headers.get("Retry-After")
        try:
            retry_seconds = max(0.0, float(retry_after)) if retry_after else None
        except (TypeError, ValueError):
            retry_seconds = None
        raise _RateLimitedHost(response.status_code, retry_seconds, host)
    response.raise_for_status()
    return _parse_rows(response.json())


class _RateLimitedHost(Exception):
    def __init__(self, status_code: int, retry_after: float | None, host: str):
        self.status_code = status_code
        self.retry_after = retry_after
        self.host = host
        super().__init__(f"{host} returned HTTP {status_code}")


async def binance_klines(symbol: str, interval: str, limit: int):
    normalized_symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized_symbol):
        raise ValueError("Invalid symbol")
    if not re.fullmatch(r"[0-9]+[smhdwM]", interval):
        raise ValueError("Invalid Binance interval")
    if not 1 <= int(limit) <= 1000:
        raise ValueError("limit must be between 1 and 1000")

    cache_key = (normalized_symbol, interval, int(limit))
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return [dict(candle) for candle in cached[1]]

    async with _cache_lock:
        now = time.monotonic()
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return [dict(candle) for candle in cached[1]]

        errors: list[str] = []
        for host in _hosts():
            try:
                candles = await _request_host(host, normalized_symbol, interval, int(limit))
                if len(_cache) >= _CACHE_MAX_ITEMS:
                    oldest_key = min(_cache, key=lambda key: _cache[key][0])
                    _cache.pop(oldest_key, None)
                _cache[cache_key] = (time.monotonic(), candles)
                return [dict(candle) for candle in candles]
            except _RateLimitedHost as exc:
                errors.append(str(exc))
                # 418 is an IP ban signal: do not retry that host.
                # For 429, respect Retry-After; only wait briefly, otherwise
                # move to another official host instead of blocking API workers.
                if exc.status_code == 429 and exc.retry_after is not None and 0 < exc.retry_after <= 1.0:
                    await asyncio.sleep(exc.retry_after)
                    try:
                        candles = await _request_host(host, normalized_symbol, interval, int(limit))
                        _cache[cache_key] = (time.monotonic(), candles)
                        return [dict(candle) for candle in candles]
                    except Exception as retry_exc:
                        errors.append(f"{host} retry failed: {retry_exc}")
            except (httpx.HTTPError, ValueError, MarketDataProviderError) as exc:
                errors.append(f"{host}: {exc}")

        detail = "; ".join(errors[-4:]) or "no Binance hosts configured"
        raise MarketDataProviderError(
            "All Binance public market-data hosts failed. "
            "The request was not retried against a host returning 418/429. "
            f"Details: {detail}"
        )
