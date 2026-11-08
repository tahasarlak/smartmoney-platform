from __future__ import annotations
import asyncio, json, logging, math, os, re, time
from typing import Any
import websockets
from .signal_journal import list_signals, update_signal_price
from .market_store import (init_market_store, list_watchlist, add_watchlist_symbol,
                           remove_watchlist_symbol, upsert_market_price, list_market_prices)

log = logging.getLogger(__name__)
ACTIVE_STATUSES = ("WAITING_ENTRY", "OPEN", "TP1_HIT", "TP2_HIT")
BINANCE_STREAM_BASE = "wss://stream.binance.com:9443/stream?streams="

def normalize_symbol(value: str) -> str:
    symbol = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", symbol):
        raise ValueError("Invalid Binance symbol, e.g. BTCUSDT.")
    return symbol

def active_symbols() -> list[str]:
    symbols: set[str] = set()
    for item in os.getenv("LIVE_MONITOR_SYMBOLS", "").split(","):
        if item.strip():
            try: symbols.add(normalize_symbol(item).lower())
            except ValueError: log.warning("Ignoring invalid monitor symbol: %r", item)
    for status in ACTIVE_STATUSES:
        for signal in list_signals(status=status, limit=500):
            raw = str(signal.get("symbol", "")).strip()
            if raw:
                try: symbols.add(normalize_symbol(raw).lower())
                except ValueError: log.warning("Ignoring invalid signal symbol: %r", raw)
    return sorted(symbols)

def build_stream_url(symbols: list[str]) -> str:
    normalized = {normalize_symbol(s).lower() for s in symbols if str(s).strip()}
    streams = "/".join(f"{s}@trade" for s in sorted(normalized))
    if not streams: raise ValueError("At least one symbol is required")
    return BINANCE_STREAM_BASE + streams

def parse_trade_message(raw: str | bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
        data = payload.get("data", payload)
        symbol = normalize_symbol(data["s"])
        price = float(data["p"])
        event_time = int(data.get("T", data.get("E", int(time.time() * 1000))))
        if not math.isfinite(price) or price <= 0: return None
        return {
            "symbol": symbol, "price": price, "event_time_ms": event_time,
            "event_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(event_time / 1000))
                + f".{event_time % 1000:03d}+00:00",
        }
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None

def apply_trade_event(event: dict[str, Any]) -> int:
    changed = 0
    for status in ACTIVE_STATUSES:
        for signal in list_signals(status=status, symbol=event["symbol"], limit=500):
            if update_signal_price(signal["id"], event["price"], event["event_time"]):
                changed += 1
    return changed

class LivePriceMonitor:
    def __init__(self, reconnect_delay: float = 3.0, refresh_symbols_seconds: int = 30):
        self.reconnect_delay = reconnect_delay
        self.refresh_symbols_seconds = refresh_symbols_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_message_at: str | None = None
        self._last_error: str | None = None
        self._messages_received = 0
        self._signals_updated = 0
        self._connected = False
        self._symbols: list[str] = []
        init_market_store()
        self._watchlist: set[str] = set(list_watchlist())
        saved_prices = list_market_prices()
        self._prices: dict[str, dict[str, Any]] = {
            item["symbol"]: {
                "symbol": item["symbol"], "price": item["price"],
                "event_time": item["event_time"], "event_time_ms": item["event_time_ms"],
            }
            for item in saved_prices
        }
        latest = max(saved_prices, key=lambda item: item["event_time_ms"], default=None)
        self._last_message_at: str | None = latest["event_time"] if latest else None

    def add_symbol(self, value: str) -> dict[str, Any]:
        symbol = normalize_symbol(value)
        self._watchlist.add(symbol)
        add_watchlist_symbol(symbol)
        return self.watchlist_status()

    def remove_symbol(self, value: str) -> dict[str, Any]:
        symbol = normalize_symbol(value)
        self._watchlist.discard(symbol)
        remove_watchlist_symbol(symbol)
        return self.watchlist_status()

    def watchlist_status(self) -> dict[str, Any]:
        return {"symbols": sorted(self._watchlist), "count": len(self._watchlist),
                "storage": "postgresql", "execution_allowed": False}

    def market_snapshot(self) -> dict[str, Any]:
        prices = list_market_prices()
        latest = max(prices, key=lambda item: item["event_time_ms"], default=None)
        return {"prices": prices, "count": len(prices),
                "updated_at": latest["updated_at"] if latest else None,
                "storage": "postgresql", "execution_allowed": False}

    async def start(self) -> dict[str, Any]:
        if self._task and not self._task.done(): return self.status()
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="binance-live-price-monitor")
        return self.status()

    async def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
        self._connected = False
        return self.status()

    def status(self) -> dict[str, Any]:
        return {"running": bool(self._task and not self._task.done()),
                "connected": self._connected, "symbols": self._symbols,
                "watchlist": sorted(self._watchlist),
                "watchlist_storage": "postgresql",
                "messages_received": self._messages_received,
                "signals_updated": self._signals_updated,
                "cached_prices": len(list_market_prices()),
                "last_message_at": self._last_message_at,
                "last_error": self._last_error, "execution_allowed": False}

    async def _run(self):
        while not self._stop.is_set():
            try:
                symbols = sorted(set(active_symbols()) | {s.lower() for s in self._watchlist})
                self._symbols = symbols
                if not symbols:
                    self._connected = False
                    try: await asyncio.wait_for(self._stop.wait(), timeout=5)
                    except asyncio.TimeoutError: pass
                    continue
                async with websockets.connect(build_stream_url(symbols), ping_interval=20,
                    ping_timeout=20, close_timeout=5, max_size=2**20) as ws:
                    self._connected = True
                    self._last_error = None
                    last_refresh = time.monotonic()
                    while not self._stop.is_set():
                        try: raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            if time.monotonic() - last_refresh >= self.refresh_symbols_seconds: break
                            continue
                        event = parse_trade_message(raw)
                        if not event: continue
                        self._messages_received += 1
                        self._last_message_at = event["event_time"]
                        self._prices[event["symbol"]] = {
                            "symbol": event["symbol"], "price": event["price"],
                            "event_time": event["event_time"],
                            "event_time_ms": event["event_time_ms"]}
                        upsert_market_price(event, provider="binance_spot")
                        self._signals_updated += apply_trade_event(event)
                        if time.monotonic() - last_refresh >= self.refresh_symbols_seconds: break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.warning("Live price monitor reconnecting: %s", self._last_error)
            finally:
                self._connected = False
            if not self._stop.is_set():
                try: await asyncio.wait_for(self._stop.wait(), timeout=self.reconnect_delay)
                except asyncio.TimeoutError: pass

live_price_monitor = LivePriceMonitor()
