from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any, Awaitable, Callable

from .historical_signal_engine import generate_historical_smc_signals
from .scanner import TIMEFRAMES

FetchKlines = Callable[[str, str, int], Awaitable[list[dict[str, Any]]]]
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")


async def evaluate_live_smc(
    symbol: str,
    fetch_klines: FetchKlines,
    *,
    limit: int = 500,
    min_quality_score: int = 65,
    min_rr: float = 2.0,
    risk_percent: float = 0.5,
    allow_counter_trend: bool = False,
    use_regime_filter: bool = True,
    reject_transition_regime: bool = True,
    require_trend_alignment: bool = True,
    reject_high_volatility: bool = False,
    decision_time: int | None = None,
) -> dict[str, Any]:
    """Evaluate the latest fully closed 5m decision using the historical SMC engine.

    This is an on-demand strategy-to-market-data bridge. It fetches public OHLC
    candles, delegates causal candle selection and SMC logic to the existing
    historical engine, and returns only signals from the latest decision
    boundary. It never writes the signal journal or submits paper/live orders.
    """
    normalized = str(symbol).strip().upper()
    if not _SYMBOL_RE.fullmatch(normalized):
        raise ValueError("Invalid symbol")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 100 <= limit <= 1000:
        raise ValueError("limit must be between 100 and 1000")
    if not isinstance(min_quality_score, int) or not 0 <= min_quality_score <= 100:
        raise ValueError("min_quality_score must be between 0 and 100")
    if not math.isfinite(float(min_rr)) or not 0.5 <= float(min_rr) <= 10:
        raise ValueError("min_rr must be between 0.5 and 10")
    if not math.isfinite(float(risk_percent)) or not 0 < float(risk_percent) <= 2:
        raise ValueError("risk_percent must be greater than 0 and at most 2")

    rows = await asyncio.gather(*(
        fetch_klines(normalized, timeframe, limit)
        for timeframe in TIMEFRAMES
    ))
    candles_by_tf = dict(zip(TIMEFRAMES, rows))

    five_minute_rows = candles_by_tf.get("5m")
    if not isinstance(five_minute_rows, list) or len(five_minute_rows) < 2:
        raise ValueError("At least two 5m candles are required")

    # Binance klines includes the currently-forming 5m candle as the final row.
    # Its open time is the close boundary of the preceding, decision-eligible bar.
    latest_boundary = (
        int(five_minute_rows[-1]["time"])
        if decision_time is None
        else int(decision_time)
    )
    if latest_boundary <= 0:
        raise ValueError("decision_time must be positive")

    generated = await asyncio.to_thread(
        generate_historical_smc_signals,
        normalized,
        candles_by_tf,
        min_quality_score=min_quality_score,
        min_rr=min_rr,
        risk_percent=risk_percent,
        allow_counter_trend=allow_counter_trend,
        max_signals=1000,
        history_limit=limit,
        use_regime_filter=use_regime_filter,
        reject_transition_regime=reject_transition_regime,
        require_trend_alignment=require_trend_alignment,
        reject_high_volatility=reject_high_volatility,
    )

    latest_signals = [
        item for item in generated.get("signals", [])
        if int(item.get("signal_time", -1)) == latest_boundary
    ]
    return {
        "status": "completed",
        "symbol": normalized,
        "provider": "Binance public market data",
        "decision_timeframe": "5m",
        "decision_time": latest_boundary,
        "candles_requested_per_timeframe": limit,
        "timeframes": list(TIMEFRAMES),
        "historical_signal_count": int(generated.get("signal_count", 0)),
        "latest_signal_count": len(latest_signals),
        "signals": latest_signals,
        "rejected_counts": generated.get("rejected_counts", {}),
        "market_regime_summary": generated.get("market_regime_summary", {}),
        "regime_filter": generated.get("regime_filter", {}),
        "lookahead_policy": generated.get("lookahead_policy", {}),
        "execution_allowed": False,
        "persistence": "not_written",
        "limitations": [
            "On-demand evaluation only; no automatic 5m scheduler is enabled in this phase.",
            "Signals are returned for inspection and are not journaled or executed.",
            "The final 5m candle supplied by Binance is treated as forming; its open time defines the latest decision boundary.",
            "Historical SMC methodology is rule-based and does not establish predictive profitability.",
        ],
    }
