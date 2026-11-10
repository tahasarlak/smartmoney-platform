"""Twelve Data price stream and strict tick-to-OHLC aggregation.

The free plan is a trial path, not a production data licence. It only works
when the provider confirms every requested subscription. No prices are invented.
"""
from __future__ import annotations
import asyncio
import json
import logging
import math
import os
import random
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import websockets

log = logging.getLogger("tradf.forex_stream")
PROVIDER = "twelvedata_price_stream"
SYMBOLS = {
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "USDCHF": "USD/CHF", "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD",
    "NZDUSD": "NZD/USD", "XAUUSD": "XAU/USD",
}
TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


class ForexStreamError(RuntimeError):
    pass


def normalize_provider_symbol(value: str) -> str | None:
    normalized = str(value or "").upper().replace("/", "").replace(" ", "")
    return normalized if normalized in SYMBOLS else None


def validate_tick(event: dict[str, Any]) -> dict[str, Any]:
    symbol = normalize_provider_symbol(event.get("symbol"))
    try:
        price = float(event["price"])
        timestamp = float(event["timestamp"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Malformed Twelve Data price event") from exc
    if symbol is None or not math.isfinite(price) or price <= 0:
        raise ValueError("Unsupported symbol or invalid price")
    if not math.isfinite(timestamp) or timestamp <= 0:
        raise ValueError("Invalid tick timestamp")
    bid = event.get("bid")
    ask = event.get("ask")
    if bid is not None:
        bid = float(bid)
        if not math.isfinite(bid) or bid <= 0 or bid > price * 1.1:
            raise ValueError("Invalid bid")
    if ask is not None:
        ask = float(ask)
        if not math.isfinite(ask) or ask <= 0 or ask < price * 0.9:
            raise ValueError("Invalid ask")
    if bid is not None and ask is not None and bid > ask:
        raise ValueError("Bid exceeds ask")
    return {
        "symbol": symbol, "price": price, "event_time_ms": int(timestamp * 1000),
        "bid": bid, "ask": ask, "provider": PROVIDER,
    }


class CandleAggregator:
    """Builds UTC OHLC candles from actual received ticks; volume is unavailable."""
    def __init__(self):
        self.current: dict[tuple[str, str], dict[str, Any]] = {}
        self.last_timestamp: dict[tuple[str, str], int] = {}

    def update(self, tick: dict[str, Any]) -> list[dict[str, Any]]:
        symbol = tick["symbol"]
        timestamp = int(tick["event_time_ms"] // 1000)
        price = float(tick["price"])
        closed: list[dict[str, Any]] = []
        for timeframe, seconds in TIMEFRAMES.items():
            bucket = timestamp // seconds * seconds
            key = (symbol, timeframe)
            current = self.current.get(key)
            previous_tick_time = self.last_timestamp.get(key)
            if previous_tick_time is not None and timestamp < previous_tick_time:
                continue
            if current is None:
                self.current[key] = {
                    "symbol": symbol, "timeframe": timeframe, "time": bucket,
                    "open": price, "high": price, "low": price, "close": price,
                    "volume": 0.0, "provider": PROVIDER,
                }
                self.last_timestamp[key] = timestamp
                continue
            if bucket < current["time"]:
                # Ignore out-of-order ticks rather than corrupt candle chronology.
                continue
            if bucket == current["time"]:
                current["high"] = max(current["high"], price)
                current["low"] = min(current["low"], price)
                current["close"] = price
                self.last_timestamp[key] = timestamp
                continue
            closed.append(dict(current))
            self.current[key] = {
                "symbol": symbol, "timeframe": timeframe, "time": bucket,
                "open": price, "high": price, "low": price, "close": price,
                "volume": 0.0, "provider": PROVIDER,
            }
            self.last_timestamp[key] = timestamp
        return closed


async def run_twelvedata_stream(
    on_tick: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    api_key: str | None = None,
    stop_event: asyncio.Event | None = None,
    on_status: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> None:
    key = (api_key or os.getenv("TWELVE_DATA_API_KEY", "")).strip()
    if not key:
        raise ForexStreamError("TWELVE_DATA_API_KEY is required")
    url = f"wss://ws.twelvedata.com/v1/quotes/price?apikey={key}"
    symbols = ",".join(SYMBOLS.values())
    delay = 2.0
    stop_event = stop_event or asyncio.Event()

    while not stop_event.is_set():
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                await ws.send(json.dumps({"action": "subscribe", "params": {"symbols": symbols}}))
                subscribed: set[str] = set()
                failed: set[str] = set()
                while not stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"action": "heartbeat"}))
                        continue
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        continue
                    event = payload.get("event")
                    if event == "subscribe-status":
                        for item in payload.get("success", []):
                            normalized = normalize_provider_symbol(item.get("symbol"))
                            if normalized:
                                subscribed.add(normalized)
                        for item in payload.get("fails", []):
                            normalized = normalize_provider_symbol(item.get("symbol"))
                            if normalized:
                                failed.add(normalized)
                        log.info("Twelve Data subscription status: subscribed=%s failed=%s",
                                 sorted(subscribed), sorted(failed))
                        if on_status is not None:
                            await on_status({"status": "ready" if subscribed == set(SYMBOLS) and not failed else "degraded",
                                             "subscribed_symbols": sorted(subscribed),
                                             "last_error": "subscription_failed" if failed else None})
                        if failed or subscribed and subscribed != set(SYMBOLS):
                            raise ForexStreamError(
                                "Provider did not confirm all eight symbols; "
                                f"subscribed={sorted(subscribed)} failed={sorted(failed)}"
                            )
                    elif event == "price":
                        tick = validate_tick(payload)
                        await on_tick(tick)
                delay = 2.0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("Forex stream disconnected: %s", type(exc).__name__)
            if on_status is not None:
                try:
                    await on_status({"status": "disconnected", "subscribed_symbols": [],
                                     "last_error": type(exc).__name__})
                except Exception:
                    pass
            await asyncio.sleep(delay + random.random())
            delay = min(60.0, delay * 2.0)
