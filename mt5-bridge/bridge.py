from __future__ import annotations

import json
import logging
import math
import os
import signal
import sys
import time
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD")
TIMEFRAME_NAMES = ("1m", "5m", "15m", "1h", "4h")
POLL_SECONDS = max(15, int(os.getenv("MT5_POLL_SECONDS", "30")))
HISTORY_BARS = min(9000, max(300, int(os.getenv("MT5_HISTORY_BARS", "7000"))))
API_BASE = os.getenv("TRADF_API_BASE_URL", "").strip().rstrip("/")
BRIDGE_TOKEN = os.getenv("TRADF_MT5_BRIDGE_TOKEN", "").strip()
BRIDGE_ID = os.getenv("MT5_BRIDGE_ID", "windows-demo-bridge-01").strip()
TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", "").strip()
SYMBOL_MAP_RAW = os.getenv("MT5_SYMBOL_MAP", "").strip()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("tradf-mt5-bridge")
STOP = False


def resolve_broker_symbol(canonical: str, available: list[str], explicit: dict[str, str]) -> str | None:
    """Resolve exact symbol first; suffix auto-detection only when unambiguous."""
    by_upper = {name.upper(): name for name in available}
    override = explicit.get(canonical)
    if override:
        return by_upper.get(override.upper())
    if canonical in by_upper:
        return by_upper[canonical]
    matches = [
        name for name in available
        if name.upper().startswith(canonical)
        and 0 < len(name) - len(canonical) <= 8
        and all(ch.isalnum() or ch in "._-" for ch in name[len(canonical):])
    ]
    return matches[0] if len(matches) == 1 else None


def parse_symbol_map(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("MT5_SYMBOL_MAP must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("MT5_SYMBOL_MAP must be a JSON object")
    result = {}
    for key, symbol in value.items():
        canonical = str(key).strip().upper()
        broker_symbol = str(symbol).strip()
        if canonical not in SYMBOLS or not broker_symbol or len(broker_symbol) > 40:
            raise ValueError(f"Invalid MT5_SYMBOL_MAP entry: {key}")
        result[canonical] = broker_symbol
    return result


class MT5Bridge:
    def __init__(self):
        if not API_BASE.startswith("https://") and not API_BASE.startswith("http://127.0.0.1") and not API_BASE.startswith("http://localhost"):
            raise RuntimeError("TRADF_API_BASE_URL must use HTTPS (HTTP is allowed only for localhost)")
        if len(BRIDGE_TOKEN) < 32:
            raise RuntimeError("TRADF_MT5_BRIDGE_TOKEN must contain at least 32 characters")
        if len(BRIDGE_ID) < 3 or len(BRIDGE_ID) > 80:
            raise RuntimeError("MT5_BRIDGE_ID must contain 3..80 characters")
        self.mt5 = None
        self.client = httpx.Client(
            base_url=API_BASE,
            timeout=httpx.Timeout(25.0, connect=10.0),
            headers={"X-TRADF-BRIDGE-TOKEN": BRIDGE_TOKEN, "User-Agent": "TRADF-MT5-Demo-Bridge/1.0"},
        )
        self.symbol_map = parse_symbol_map(SYMBOL_MAP_RAW)
        self.resolved: dict[str, str] = {}
        self.terminal_version = "unknown"
        self.broker_server = "unknown"

    def connect(self):
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError("MetaTrader5 package missing; install mt5-bridge/requirements.txt") from exc
        self.mt5 = mt5
        if TERMINAL_PATH:
            ok = mt5.initialize(path=TERMINAL_PATH, timeout=60000)
        else:
            ok = mt5.initialize(timeout=60000)
        if not ok:
            raise RuntimeError(f"MetaTrader5 initialize failed: {mt5.last_error()}")
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        if account is None or terminal is None:
            raise RuntimeError(f"MT5 terminal/account info unavailable: {mt5.last_error()}")
        if not terminal.connected:
            raise RuntimeError("MT5 terminal is not connected to the broker")
        if account.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise RuntimeError("Safety stop: connected MT5 account is not DEMO")
        self.broker_server = str(account.server or "demo-server")[:120]
        version = mt5.version()
        self.terminal_version = ".".join(map(str, version)) if version else "unknown"
        available = [item.name for item in (mt5.symbols_get() or ())]
        for canonical in SYMBOLS:
            resolved = resolve_broker_symbol(canonical, available, self.symbol_map)
            if resolved and mt5.symbol_select(resolved, True):
                self.resolved[canonical] = resolved
            else:
                log.warning("Symbol not available or ambiguous: %s (set MT5_SYMBOL_MAP if broker uses a suffix)", canonical)
        if not self.resolved:
            raise RuntimeError("None of the configured forex/gold symbols were resolved in Market Watch")
        log.info("Connected to MT5 DEMO; resolved %d/%d symbols", len(self.resolved), len(SYMBOLS))

    def _ensure_demo(self):
        account = self.mt5.account_info()
        terminal = self.mt5.terminal_info()
        if account is None or terminal is None or not terminal.connected:
            raise RuntimeError(f"MT5 terminal disconnected: {self.mt5.last_error()}")
        if account.trade_mode != self.mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise RuntimeError("Safety stop: MT5 account changed and is no longer DEMO")

    def _heartbeat(self):
        self.client.post("/api/v1/mt5/bridge/heartbeat", json={
            "bridge_id": BRIDGE_ID,
            "broker_server": self.broker_server,
            "terminal_version": self.terminal_version,
            "account_mode": "demo",
        }).raise_for_status()

    def _rates(self, broker_symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
        constants = {
            "1m": self.mt5.TIMEFRAME_M1,
            "5m": self.mt5.TIMEFRAME_M5,
            "15m": self.mt5.TIMEFRAME_M15,
            "1h": self.mt5.TIMEFRAME_H1,
            "4h": self.mt5.TIMEFRAME_H4,
        }
        rates = self.mt5.copy_rates_from_pos(broker_symbol, constants[timeframe], 0, count)
        if rates is None:
            raise RuntimeError(f"MT5 history unavailable for {broker_symbol} {timeframe}: {self.mt5.last_error()}")
        candles = []
        for rate in rates:
            row = {
                "time": int(rate["time"]),
                "open": float(rate["open"]),
                "high": float(rate["high"]),
                "low": float(rate["low"]),
                "close": float(rate["close"]),
                "volume": float(rate["tick_volume"]),
                "spread_points": int(rate["spread"]),
            }
            if not all(math.isfinite(row[k]) for k in ("open", "high", "low", "close", "volume")):
                continue
            if min(row["open"], row["high"], row["low"], row["close"]) <= 0:
                continue
            candles.append(row)
        candles.sort(key=lambda x: x["time"])
        deduped = {item["time"]: item for item in candles}
        return [deduped[key] for key in sorted(deduped)]

    def _post_series(self, series: list[dict[str, Any]]):
        if not series:
            return
        response = self.client.post("/api/v1/mt5/bridge/candles", json={
            "bridge_id": BRIDGE_ID,
            "broker_server": self.broker_server,
            "terminal_version": self.terminal_version,
            "account_mode": "demo",
            "series": series,
        })
        response.raise_for_status()
        result = response.json()
        log.info("Market data accepted: %s series, %s candle rows", result.get("series_count"), result.get("candle_rows_upserted"))

    def initial_backfill(self):
        self._ensure_demo()
        total = 0
        for canonical, broker_symbol in self.resolved.items():
            batch = []
            for timeframe in TIMEFRAME_NAMES:
                candles = self._rates(broker_symbol, timeframe, HISTORY_BARS)
                if len(candles) < 51:
                    log.warning("Skipping %s %s: only %d bars available", canonical, timeframe, len(candles))
                    continue
                batch.append({
                    "symbol": canonical,
                    "broker_symbol": broker_symbol,
                    "timeframe": timeframe,
                    "candles": candles,
                })
                total += len(candles)
            if batch:
                self._post_series(batch)
        log.info("Initial history sync complete: %d candles; requested history bars per series=%d", total, HISTORY_BARS)

    def poll_once(self):
        self._ensure_demo()
        self._heartbeat()
        batch = []
        for canonical, broker_symbol in self.resolved.items():
            for timeframe in TIMEFRAME_NAMES:
                candles = self._rates(broker_symbol, timeframe, 3)
                if candles:
                    batch.append({
                        "symbol": canonical,
                        "broker_symbol": broker_symbol,
                        "timeframe": timeframe,
                        "candles": candles,
                    })
        if batch:
            self._post_series(batch)

    def run(self):
        self.connect()
        self.initial_backfill()
        log.info("Read-only MT5 DEMO market bridge running; order execution is not implemented.")
        while not STOP:
            started = time.monotonic()
            try:
                self.poll_once()
            except Exception as exc:
                log.exception("Bridge polling error: %s", exc)
                # Do not report a healthy heartbeat after a failed poll.
                time.sleep(min(15, POLL_SECONDS))
                try:
                    self.mt5.shutdown()
                except Exception:
                    pass
                self.connect()
            elapsed = time.monotonic() - started
            time.sleep(max(1, POLL_SECONDS - elapsed))

    def close(self):
        try:
            if self.mt5:
                self.mt5.shutdown()
        finally:
            self.client.close()


def _stop(_signum, _frame):
    global STOP
    STOP = True


def main():
    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    bridge = MT5Bridge()
    try:
        bridge.run()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("MT5 bridge stopped safely: %s", exc)
        sys.exit(1)
