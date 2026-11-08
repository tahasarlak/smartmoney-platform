from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, field_validator

from .data_quality import validate_candle_series
from .scanner import TIMEFRAMES, scan_symbol
from .market_regime import analyze_market_regime

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
_ACTIVE_SIGNAL_STATUSES = {"WAITING_ENTRY", "OPEN", "TP1_HIT", "TP2_HIT"}
_INTERVAL_SECONDS = {"4h": 14400, "1h": 3600, "15m": 900, "5m": 300, "1m": 60}


class V8ScanRequest(BaseModel):
    symbols: list[str] | None = Field(default=None, max_length=30)
    limit: int = Field(default=300, ge=100, le=1000)
    persist_signals: bool = False

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            symbol = str(raw).strip().upper()
            if not _SYMBOL_RE.fullmatch(symbol):
                raise ValueError(f"Invalid symbol format: {raw}")
            if symbol not in seen:
                result.append(symbol)
                seen.add(symbol)
        if not result:
            raise ValueError("At least one unique symbol is required")
        return result


class V8StartRequest(V8ScanRequest):
    interval_seconds: int = Field(default=60, ge=30, le=3600)
    persist_signals: bool = True


def _atr(candles: list[dict[str, Any]], period: int = 14) -> float:
    closed = candles[:-1]
    if len(closed) < 2:
        return 0.0
    tr_values = []
    for index in range(1, len(closed)):
        previous_close = float(closed[index - 1]["close"])
        current = closed[index]
        tr_values.append(max(
            float(current["high"]) - float(current["low"]),
            abs(float(current["high"]) - previous_close),
            abs(float(current["low"]) - previous_close),
        ))
    sample = tr_values[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def _make_plan(
    symbol: str,
    scenario: dict[str, Any],
    candles_by_tf: dict[str, list[dict[str, Any]]],
    min_rr: float,
    risk_percent: float,
) -> dict[str, Any] | None:
    zone = scenario.get("zone")
    if not isinstance(zone, dict):
        return None

    direction = scenario.get("direction")
    if direction not in ("bullish", "bearish"):
        return None

    try:
        low = float(zone["low"])
        high = float(zone["high"])
        price = float(candles_by_tf["5m"][-2]["close"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None

    if not (0 < low < high and price > 0):
        return None

    atr = _atr(candles_by_tf["5m"])
    if atr <= 0:
        return None

    # Keep zones that price has not fully crossed. A price inside the zone
    # is a live retest, not an invalid setup.
    if direction == "bullish" and price < low:
        return None
    if direction == "bearish" and price > high:
        return None

    entry = (low + high) / 2.0
    buffer = max(atr * 0.15, price * 0.0001)
    stop = low - buffer if direction == "bullish" else high + buffer
    risk_distance = abs(entry - stop)
    if risk_distance <= 0:
        return None

    # TP2 satisfies the configured minimum RR; targets are planning levels,
    # not claims about where liquidity will necessarily be available.
    rr2 = max(1.0, float(min_rr))
    rr3 = max(rr2 + 1.0, 3.0)
    multiples = (1.0, rr2, rr3)
    targets = []
    for index, multiple in enumerate(multiples, start=1):
        target = entry + risk_distance * multiple if direction == "bullish" else entry - risk_distance * multiple
        if target <= 0:
            return None
        targets.append({
            "name": f"TP{index}",
            "price": round(target, 10),
            "risk_reward": round(multiple, 2),
        })

    # Do not publish a fresh pullback plan after its first target has already
    # been crossed, or after price has invalidated the stop side.
    tp1 = targets[0]["price"]
    if direction == "bullish" and (price >= tp1 or price <= stop):
        return None
    if direction == "bearish" and (price <= tp1 or price >= stop):
        return None

    confirmation = scenario.get("confirmation", "unknown")
    quality = max(0, min(100, int(scenario.get("quality_score", 0))))
    current_state = "pending_retest"
    if low <= price <= high:
        current_state = "zone_active"

    reasons = list(scenario.get("reasons") or [])
    reasons.extend([
        f"5M {zone.get('type', 'SMC')} zone is available for a retest",
        f"Entry is the zone midpoint; stop includes a 0.15 ATR buffer",
        f"TP2 is planned at {rr2:g}R to satisfy the configured minimum RR",
    ])

    return {
        "symbol": symbol,
        "status": current_state,
        "direction": direction,
        "setup_class": scenario.get("setup_class", "mixed_context"),
        "quality_score": quality,
        "confirmation": confirmation,
        "entry_confirmation_required": [
            "5M price retest of the selected zone",
            "directional rejection on a fully closed 5M candle",
            "BOS or CHoCH on that same closed 5M candle",
        ],
        "zone": {
            "type": zone.get("type"),
            "low": low,
            "high": high,
            "formed_at": zone.get("formed_at"),
            "status": zone.get("status"),
        },
        "current_price": round(price, 10),
        "entry": round(entry, 10),
        "stop_loss": round(stop, 10),
        "risk_distance": round(risk_distance, 10),
        "take_profits": targets,
        "minimum_rr_requested": float(min_rr),
        "risk_percent_setting": float(risk_percent),
        "rr_filter_passed": targets[1]["risk_reward"] >= float(min_rr),
        "estimated_win_probability": None,
        "probability_status": "not_calibrated_no_win_probability_claim",
        "reasons": reasons,
        "invalidation": "Invalidate if a closed 5M candle closes beyond the far side of the zone before entry.",
        "execution_allowed": False,
        "note": "Research signal only. No broker order is created or sent.",
    }


def _find_duplicate_signal(list_signals_fn: Callable[..., list[dict[str, Any]]], plan: dict[str, Any]) -> dict[str, Any] | None:
    zone = plan.get("zone") or {}
    low, high = float(zone.get("low", 0)), float(zone.get("high", 0))
    for status in _ACTIVE_SIGNAL_STATUSES:
        for existing in list_signals_fn(status=status, symbol=plan["symbol"], limit=500):
            if existing.get("direction") != plan.get("direction"):
                continue
            old_low, old_high = existing.get("zone_low"), existing.get("zone_high")
            if old_low is None or old_high is None:
                continue
            scale = max(abs(low), abs(high), 1.0)
            if abs(float(old_low) - low) / scale <= 1e-8 and abs(float(old_high) - high) / scale <= 1e-8:
                return existing
    return None


async def scan_symbols_v8(
    symbols: list[str],
    limit: int,
    fetch_klines: Callable[[str, str, int], Awaitable[list[dict[str, Any]]]],
    analyze_smc_fn: Callable[..., dict[str, Any]],
    settings: dict[str, Any] | None = None,
    persist_signals: bool = False,
    create_signal_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    list_signals_fn: Callable[..., list[dict[str, Any]]] | None = None,
    max_concurrency: int = 4,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    settings = settings or {}
    min_quality = int(settings.get("min_quality_score", 50))
    min_rr = float(settings.get("min_rr", 2.0))
    risk_percent = float(settings.get("risk_per_trade_pct", 0.5))
    allow_counter = bool(settings.get("allow_counter_trend", True))

    if not 1 <= len(symbols) <= 30:
        raise ValueError("symbols must contain between 1 and 30 entries")
    if not 100 <= limit <= 1000:
        raise ValueError("limit must be between 100 and 1000")
    if not 1 <= max_concurrency <= 6:
        raise ValueError("max_concurrency must be between 1 and 6")
    if not 0 <= min_quality <= 100:
        raise ValueError("min_quality_score must be between 0 and 100")
    if not 0.5 <= min_rr <= 10:
        raise ValueError("min_rr must be between 0.5 and 10")
    if not 0 < risk_percent <= 2:
        raise ValueError("risk_per_trade_pct must be greater than 0 and at most 2")

    normalized = list(dict.fromkeys(str(item).strip().upper() for item in symbols))
    if any(not _SYMBOL_RE.fullmatch(item) for item in normalized):
        raise ValueError("One or more symbols have invalid format")
    if persist_signals and (create_signal_fn is None or list_signals_fn is None):
        raise ValueError("Signal journal functions are required when persist_signals is enabled")

    semaphore = asyncio.Semaphore(max_concurrency)
    scan_epoch = int(now_epoch if now_epoch is not None else time.time())

    async def scan_one(symbol: str) -> dict[str, Any]:
        async with semaphore:
            try:
                fetched = await asyncio.gather(*[
                    fetch_klines(symbol, timeframe, limit) for timeframe in TIMEFRAMES
                ])
                candles_by_tf = dict(zip(TIMEFRAMES, fetched))
                checks = {
                    timeframe: validate_candle_series(candles_by_tf[timeframe], timeframe, scan_epoch)
                    for timeframe in TIMEFRAMES
                }
                invalid = next((tf for tf, check in checks.items() if not check["valid"]), None)
                if invalid:
                    return {
                        "symbol": symbol,
                        "status": "data_rejected",
                        "failed_timeframe": invalid,
                        "reason": checks[invalid]["reason"],
                        "data_quality": checks,
                    }

                # Regime classification is computed independently from SMC.
                # It adds context to the setup without pretending to predict outcomes.
                regimes = {
                    timeframe: analyze_market_regime(candles_by_tf[timeframe], timeframe)
                    for timeframe in TIMEFRAMES
                }
                analyses = {
                    timeframe: analyze_smc_fn(symbol, candles_by_tf[timeframe], swing_length=3)
                    for timeframe in TIMEFRAMES
                }
                scan = scan_symbol(
                    symbol,
                    candles_by_tf,
                    analyses,
                    settings={
                        "min_quality_score": min_quality,
                        "min_rr": min_rr,
                        "allow_counter_trend": allow_counter,
                    },
                    regimes=regimes,
                )

                scenarios = []
                journaled = []
                for scenario in scan.get("scenarios", []):
                    plan = _make_plan(symbol, scenario, candles_by_tf, min_rr, risk_percent)
                    regime_context = {
                        "higher_timeframe": regimes["4h"],
                        "confirmation_timeframe": regimes["15m"],
                        "entry_timeframe": regimes["5m"],
                    }
                    item = {**scenario, "plan": plan, "regime_context": regime_context}
                    if regimes["4h"]["volatility_regime"] == "expanded":
                        item.setdefault("risk_context", []).append(
                            "4H volatility is expanded relative to its recent baseline"
                        )
                    if regimes["15m"]["volume_participation"] == "low":
                        item.setdefault("risk_context", []).append(
                            "15M volume participation is below its recent baseline"
                        )
                    if regimes["4h"]["regime"] == "ranging":
                        item.setdefault("risk_context", []).append(
                            "4H market regime is ranging; directional follow-through may be less reliable"
                        )
                    if plan is None:
                        scenarios.append(item)
                        continue

                    # A confirmed trigger is distinguished from a zone-only watchlist idea.
                    confirmation = scenario.get("confirmation")
                    item["signal_state"] = (
                        "ready_for_review"
                        if confirmation == "confirmed_trigger"
                        and int(scenario.get("quality_score", 0)) >= min_quality
                        else "retest_detected_waiting_structure"
                        if confirmation == "retest_detected_waiting_structure"
                        else "developing"
                        if confirmation in ("developing", "zone_waiting")
                        else "watchlist"
                    )

                    if persist_signals and item["signal_state"] == "ready_for_review":
                        duplicate = _find_duplicate_signal(list_signals_fn, plan)
                        if duplicate:
                            item["journal"] = {"saved": False, "duplicate": True, "signal": duplicate}
                        else:
                            saved = create_signal_fn(plan)
                            item["journal"] = {"saved": True, "duplicate": False, "signal": saved}
                            journaled.append(saved["id"])
                    scenarios.append(item)

                return {
                    "symbol": symbol,
                    "status": "scanned",
                    "primary_bias": scan.get("primary_bias"),
                    "higher_timeframe_context": scan.get("higher_timeframe_context"),
                    "current_price": scan.get("current_price_5m"),
                    "quality_score": max((int(x.get("quality_score", 0)) for x in scenarios), default=0),
                    "scenarios": scenarios,
                    "market_regime": regimes,
                    "data_quality": checks,
                    "journaled_signal_ids": journaled,
                    "estimated_win_probability": None,
                    "execution_allowed": False,
                }
            except Exception as exc:
                return {
                    "symbol": symbol,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "execution_allowed": False,
                }

    results = await asyncio.gather(*(scan_one(symbol) for symbol in normalized))
    scanned = [item for item in results if item["status"] == "scanned"]
    rejected = [item for item in results if item["status"] == "data_rejected"]
    errors = [item for item in results if item["status"] == "error"]
    opportunities = []
    for result in scanned:
        for scenario in result.get("scenarios", []):
            if scenario.get("plan") is not None:
                opportunities.append({
                    "symbol": result["symbol"],
                    "primary_bias": result.get("primary_bias"),
                    **scenario,
                })
    opportunities.sort(
        key=lambda item: (
            bool((item.get("quality_assessment") or {}).get("review_eligible")),
            int((item.get("quality_assessment") or {}).get("independent_confluence_count", 0)),
            int(item.get("quality_score", 0)),
            item.get("confirmation") == "confirmed_trigger",
        ),
        reverse=True,
    )

    return {
        "engine_version": "smartmoney-intelligence-v9.0",
        "quality_methodology_version": "signal-quality-1.0",
        "market_regime_methodology_version": "market-regime-1.0",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "requested_symbols": normalized,
        "summary": {
            "requested": len(normalized),
            "scanned": len(scanned),
            "data_rejected": len(rejected),
            "errors": len(errors),
            "opportunities": len(opportunities),
            "ready_for_review": sum(x.get("signal_state") == "ready_for_review" for x in opportunities),
            "journaled": sum(len(x.get("journaled_signal_ids", [])) for x in scanned),
            "expanded_volatility_symbols": sum(
                1 for item in scanned
                if item.get("market_regime", {}).get("4h", {}).get("volatility_regime") == "expanded"
            ),
            "ranging_market_symbols": sum(
                1 for item in scanned
                if item.get("market_regime", {}).get("4h", {}).get("regime") == "ranging"
            ),
        },
        "opportunities": opportunities,
        "results": results,
        "estimated_win_probability": None,
        "execution_allowed": False,
        "note": "Rule-based research engine. A review-ready setup requires a zone retest, a directional rejection, and BOS/CHoCH on the same closed 5M candle. Market-regime metrics are contextual filters, not predictive probabilities. No broker orders are sent.",
    }


class V8IntelligenceService:
    def __init__(
        self,
        fetch_klines: Callable[[str, str, int], Awaitable[list[dict[str, Any]]]],
        analyze_smc_fn: Callable[..., dict[str, Any]],
        create_signal_fn: Callable[[dict[str, Any]], dict[str, Any]],
        list_signals_fn: Callable[..., list[dict[str, Any]]],
    ):
        self.fetch_klines = fetch_klines
        self.analyze_smc_fn = analyze_smc_fn
        self.create_signal_fn = create_signal_fn
        self.list_signals_fn = list_signals_fn
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._symbols: list[str] = []
        self._interval_seconds = 60
        self._limit = 300
        self._persist_signals = True
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_scan_at: str | None = None
        self._scans_completed = 0

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._task and not self._task.done()),
            "symbols": list(self._symbols),
            "interval_seconds": self._interval_seconds,
            "persist_signals": self._persist_signals,
            "scans_completed": self._scans_completed,
            "last_scan_at": self._last_scan_at,
            "last_error": self._last_error,
            "last_summary": (self._last_result or {}).get("summary"),
            "execution_allowed": False,
        }

    def latest(self) -> dict[str, Any] | None:
        return self._last_result

    async def scan_once(self, symbols: list[str], limit: int, settings: dict[str, Any],
                        persist_signals: bool = False) -> dict[str, Any]:
        async with self._lock:
            result = await scan_symbols_v8(
                symbols=symbols,
                limit=limit,
                fetch_klines=self.fetch_klines,
                analyze_smc_fn=self.analyze_smc_fn,
                settings=settings,
                persist_signals=persist_signals,
                create_signal_fn=self.create_signal_fn,
                list_signals_fn=self.list_signals_fn,
            )
            self._last_result = result
            self._last_scan_at = result["scanned_at"]
            self._last_error = None
            self._scans_completed += 1
            return result

    async def start(self, symbols: list[str], limit: int, interval_seconds: int,
                    settings: dict[str, Any], persist_signals: bool = True) -> dict[str, Any]:
        normalized = list(dict.fromkeys(str(x).strip().upper() for x in symbols))
        if not 1 <= len(normalized) <= 30 or any(not _SYMBOL_RE.fullmatch(x) for x in normalized):
            raise ValueError("Provide 1 to 30 valid symbols")
        if not 100 <= limit <= 1000:
            raise ValueError("limit must be between 100 and 1000")
        if not 30 <= interval_seconds <= 3600:
            raise ValueError("interval_seconds must be between 30 and 3600")
        if self._task and not self._task.done():
            return self.status()
        self._symbols = normalized
        self._limit = limit
        self._interval_seconds = interval_seconds
        self._persist_signals = persist_signals
        self._settings = dict(settings)
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="smartmoney-v8-scanner")
        return self.status()

    async def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return self.status()

    async def _run(self):
        while not self._stop.is_set():
            try:
                await self.scan_once(
                    self._symbols,
                    self._limit,
                    self._settings,
                    persist_signals=self._persist_signals,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except asyncio.TimeoutError:
                pass
