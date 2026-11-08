from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from .live_strategy_pipeline import evaluate_live_smc
from .market_data import binance_klines
from .market_store import list_watchlist
from .signal_journal import create_signal

log = logging.getLogger(__name__)

EvaluateFn = Callable[..., Awaitable[dict[str, Any]]]
PersistFn = Callable[..., dict[str, Any]]
SymbolsFn = Callable[[], list[str]]


def live_signal_idempotency_key(plan: dict[str, Any]) -> str:
    """Stable key for one symbol/setup/direction on one closed decision candle."""
    symbol = str(plan.get("symbol", "")).strip().upper()
    signal_time = int(plan.get("signal_time", 0))
    direction = str(plan.get("direction", "")).strip().lower()
    setup = str(plan.get("setup_class", "")).strip().lower()
    if not symbol or signal_time <= 0 or direction not in ("bullish", "bearish"):
        raise ValueError("Signal requires symbol, positive signal_time and valid direction")
    raw = f"{symbol}|{signal_time}|{direction}|{setup}"
    return "live_smc_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:31]


def persist_live_signal(plan: dict[str, Any]) -> dict[str, Any]:
    key = live_signal_idempotency_key(plan)
    return create_signal(
        plan,
        visibility="public",
        source=key,
        idempotency_key=key,
    )


def configured_symbols() -> list[str]:
    symbols = set(list_watchlist())
    symbols.update(
        item.strip().upper()
        for item in os.getenv("LIVE_SMC_SYMBOLS", "").split(",")
        if item.strip()
    )
    return sorted(symbols)


class LiveSignalMonitor:
    """Five-minute, close-boundary SMC evaluator with idempotent journal writes.

    The monitor only creates research signals in the existing Signal Journal.
    It never opens paper orders or submits exchange orders.
    """

    def __init__(
        self,
        *,
        evaluate_fn: EvaluateFn = evaluate_live_smc,
        persist_fn: PersistFn = persist_live_signal,
        symbols_fn: SymbolsFn = configured_symbols,
        interval_seconds: int = 300,
        boundary_delay_seconds: float = 2.0,
        limit: int = 500,
        min_quality_score: int = 65,
        min_rr: float = 2.0,
        risk_percent: float = 0.5,
    ):
        if interval_seconds != 300:
            raise ValueError("Phase 11.2 decision interval is fixed at 300 seconds")
        if boundary_delay_seconds < 0 or boundary_delay_seconds > 30:
            raise ValueError("boundary_delay_seconds must be between 0 and 30")
        if not 100 <= limit <= 1000:
            raise ValueError("limit must be between 100 and 1000")
        self.evaluate_fn = evaluate_fn
        self.persist_fn = persist_fn
        self.symbols_fn = symbols_fn
        self.interval_seconds = interval_seconds
        self.boundary_delay_seconds = float(boundary_delay_seconds)
        self.limit = limit
        self.min_quality_score = min_quality_score
        self.min_rr = min_rr
        self.risk_percent = risk_percent
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._running_cycle = False
        self._cycles = 0
        self._symbols_checked = 0
        self._signals_created = 0
        self._signals_deduplicated = 0
        self._signals_rejected = 0
        self._last_cycle_at: str | None = None
        self._last_error: str | None = None
        self._last_results: list[dict[str, Any]] = []

    async def start(self) -> dict[str, Any]:
        if self._task and not self._task.done():
            return self.status()
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="live-smc-signal-monitor")
        return self.status()

    async def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._running_cycle = False
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._task and not self._task.done()),
            "running_cycle": self._running_cycle,
            "interval_seconds": self.interval_seconds,
            "boundary_delay_seconds": self.boundary_delay_seconds,
            "cycles": self._cycles,
            "symbols_checked": self._symbols_checked,
            "signals_created": self._signals_created,
            "signals_deduplicated": self._signals_deduplicated,
            "signals_rejected": self._signals_rejected,
            "last_cycle_at": self._last_cycle_at,
            "last_error": self._last_error,
            "last_results": list(self._last_results),
            "persistence": "postgresql_signal_journal",
            "execution_allowed": False,
        }

    async def run_once(self) -> dict[str, Any]:
        if self._running_cycle:
            return {"status": "skipped", "reason": "cycle_already_running"}
        self._running_cycle = True
        results: list[dict[str, Any]] = []
        created = deduplicated = rejected = checked = 0
        try:
            symbols = await asyncio.to_thread(self.symbols_fn)
            normalized = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
            for symbol in normalized:
                checked += 1
                try:
                    evaluation = await self.evaluate_fn(
                        symbol,
                        binance_klines,
                        limit=self.limit,
                        min_quality_score=self.min_quality_score,
                        min_rr=self.min_rr,
                        risk_percent=self.risk_percent,
                        use_regime_filter=True,
                    )
                    symbol_created = symbol_deduplicated = symbol_rejected = 0
                    for plan in evaluation.get("signals", []):
                        try:
                            saved = await asyncio.to_thread(self.persist_fn, plan)
                            if saved.get("deduplicated"):
                                deduplicated += 1
                                symbol_deduplicated += 1
                            else:
                                created += 1
                                symbol_created += 1
                        except (ValueError, KeyError, TypeError) as exc:
                            rejected += 1
                            symbol_rejected += 1
                            log.warning("Live SMC plan rejected for %s: %s", symbol, exc)
                    results.append({
                        "symbol": symbol,
                        "status": "completed",
                        "decision_time": evaluation.get("decision_time"),
                        "latest_signal_count": len(evaluation.get("signals", [])),
                        "created": symbol_created,
                        "deduplicated": symbol_deduplicated,
                        "rejected": symbol_rejected,
                    })
                except Exception as exc:
                    self._last_error = f"{symbol}: {type(exc).__name__}: {exc}"
                    log.exception("Live SMC evaluation failed for %s", symbol)
                    results.append({
                        "symbol": symbol,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    })
            self._cycles += 1
            self._symbols_checked += checked
            self._signals_created += created
            self._signals_deduplicated += deduplicated
            self._signals_rejected += rejected
            self._last_cycle_at = datetime.now(timezone.utc).isoformat()
            self._last_results = results[-100:]
            if not any(item["status"] == "failed" for item in results):
                self._last_error = None
            return {
                "status": "completed",
                "symbols_checked": checked,
                "signals_created": created,
                "signals_deduplicated": deduplicated,
                "signals_rejected": rejected,
                "results": results,
                "execution_allowed": False,
            }
        finally:
            self._running_cycle = False

    def _seconds_to_next_boundary(self) -> float:
        now = time.time()
        next_boundary = (int(now // self.interval_seconds) + 1) * self.interval_seconds
        return max(0.0, next_boundary - now + self.boundary_delay_seconds)

    async def _run(self) -> None:
        while not self._stop.is_set():
            delay = self._seconds_to_next_boundary()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                continue
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                break
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.exception("Live SMC monitor cycle failed")


live_signal_monitor = LiveSignalMonitor()
