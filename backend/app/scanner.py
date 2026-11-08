from __future__ import annotations
from typing import Any

TIMEFRAMES = ("4h", "1h", "15m", "5m", "1m")

def _closed_last(candles: list[dict[str, Any]]) -> dict[str, Any]:
    if len(candles) < 2:
        raise ValueError("At least two candles are required")
    return candles[-2]

def _latest_retest_rejection(
    candles: list[dict[str, Any]], direction: str, low: float, high: float
) -> bool:
    """True only when the latest CLOSED 5M candle taps the zone and rejects it."""
    if len(candles) < 3:
        return False
    previous, last = candles[-3], candles[-2]  # exclude the still-forming candle
    try:
        touched = float(last["low"]) <= high and float(last["high"]) >= low
        opened, closed = float(last["open"]), float(last["close"])
        previous_close = float(previous["close"])
    except (KeyError, TypeError, ValueError):
        return False
    if not touched:
        return False
    if direction == "bullish":
        return closed > high and closed > opened and closed > previous_close
    return closed < low and closed < opened and closed < previous_close


def _valid_zone(
    z: dict[str, Any], direction: str, price: float, atr: float,
    candles: list[dict[str, Any]] | None = None
) -> bool:
    if z.get("direction") != direction or z.get("type") not in ("FVG", "ORDER_BLOCK_CANDIDATE"):
        return False
    try:
        lo, hi = float(z["low"]), float(z["high"])
    except (KeyError, TypeError, ValueError):
        return False
    if not lo < hi or atr <= 0 or (hi-lo)/atr > 2.5:
        return False

    status = z.get("status")
    if status in ("unmitigated", "candidate_requires_retest_and_validation"):
        pass
    elif status == "mitigated":
        # A mitigated FVG is eligible only for a fresh, confirmed rejection
        # on the latest closed 5M candle; old historical mitigations are ignored.
        if candles is None or not _latest_retest_rejection(candles, direction, lo, hi):
            return False
    else:
        return False

    # Reject only when price has already crossed beyond the far edge.
    return lo <= price if direction == "bullish" else hi >= price

def _events(analysis: dict[str, Any], event_type: str, direction: str) -> list[dict]:
    return [e for e in analysis.get("events", [])
            if e.get("type") == event_type and e.get("direction") == direction]

def _zones(analysis: dict[str, Any], direction: str) -> list[dict]:
    return [z for z in analysis.get("zones", []) if z.get("direction") == direction]

def scan_symbol(symbol: str, candles_by_tf: dict[str, list[dict[str, Any]]],
                analyses: dict[str, dict[str, Any]], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create watchlist scenarios, not trade orders or fabricated win probabilities."""
    settings = settings or {}
    min_quality = int(settings.get("min_quality_score", 50))
    min_rr = float(settings.get("min_rr", 2.0))
    allow_counter = bool(settings.get("allow_counter_trend", True))
    if not 0 <= min_quality <= 100:
        raise ValueError("min_quality_score must be between 0 and 100")
    if not 0.5 <= min_rr <= 10:
        raise ValueError("min_rr must be between 0.5 and 10")
    for tf in TIMEFRAMES:
        if tf not in candles_by_tf or len(candles_by_tf[tf]) < 51:
            raise ValueError(f"At least 51 candles are required for {tf}")
        if tf not in analyses:
            raise ValueError(f"Missing analysis for {tf}")

    s4 = analyses["4h"].get("structure", "range")
    s1 = analyses["1h"].get("structure", "range")
    if s4 == s1 and s4 in ("bullish", "bearish"):
        primary, context = s4, "aligned"
    elif s4 in ("bullish", "bearish") and s1 == "range":
        primary, context = s4, "partially_aligned"
    elif s1 in ("bullish", "bearish") and s4 == "range":
        primary, context = s1, "partially_aligned"
    elif s4 in ("bullish", "bearish") and s1 in ("bullish", "bearish"):
        primary, context = "range", "conflicted"
    else:
        primary, context = "range", "range"

    current = float(_closed_last(candles_by_tf["5m"])["close"])
    atr = float(analyses["5m"].get("atr") or 0)
    if atr <= 0:
        # Derive a basic true-range average if the analysis response does not expose ATR.
        rows = candles_by_tf["5m"][:-1]
        tr = []
        for i in range(1, len(rows)):
            prev = float(rows[i-1]["close"])
            tr.append(max(float(rows[i]["high"])-float(rows[i]["low"]),
                          abs(float(rows[i]["high"])-prev),
                          abs(float(rows[i]["low"])-prev)))
        atr = sum(tr[-14:])/len(tr[-14:]) if tr else 0.0

    scenarios = []
    for direction in ("bullish", "bearish"):
        counter = primary not in ("range", direction)
        if counter and not allow_counter:
            continue
        score = 25
        score_breakdown = {"base": 25}
        reasons = []
        if primary == direction:
            score += 18
            score_breakdown["higher_timeframe_alignment"] = 18
            reasons.append(f"Higher-timeframe bias supports {direction}")
        elif counter:
            score -= 8
            score_breakdown["counter_trend_penalty"] = -8
            reasons.append(f"Counter-trend against {primary} higher-timeframe bias")
        else:
            reasons.append("Higher-timeframe structure is neutral or conflicted")

        if analyses["15m"].get("structure") == direction:
            score += 8
            score_breakdown["15m_structure"] = 8
            reasons.append("15M structure agrees")
        if analyses["5m"].get("structure") == direction:
            score += 8
            score_breakdown["5m_structure"] = 8
            reasons.append("5M structure agrees")
        if analyses["1m"].get("structure") == direction:
            score += 3
            score_breakdown["1m_structure"] = 3
            reasons.append("1M structure agrees")

        sweep = bool(_events(analyses["15m"], "LIQUIDITY_SWEEP", direction))
        bos = bool(_events(analyses["5m"], "BOS", direction))
        choch = bool(_events(analyses["5m"], "CHoCH", direction))
        one_minute_shift = bool(_events(analyses["1m"], "CHoCH", direction))
        if sweep:
            score += 15
            score_breakdown["15m_liquidity_sweep"] = 15
            reasons.append("15M liquidity sweep detected")
        if bos:
            score += 15
            score_breakdown["5m_bos"] = 15
            reasons.append("5M BOS detected")
        if choch:
            score += 12
            score_breakdown["5m_choch"] = 12
            reasons.append("5M CHoCH detected")
        if one_minute_shift:
            score += 5
            score_breakdown["1m_choch"] = 5
            reasons.append("1M CHoCH detected")

        valid_zones = [z for z in _zones(analyses["5m"], direction)
                       if _valid_zone(z, direction, current, atr, candles_by_tf["5m"])]
        if valid_zones:
            score += 10
            score_breakdown["valid_5m_retest_zone"] = 10
            reasons.append("Valid 5M unmitigated retest zone found")
        elif _zones(analyses["15m"], direction):
            reasons.append("15M zones exist, but no valid 5M entry zone is confirmed")

        score = max(0, min(100, score))
        # A watchlist candidate needs an actual price reference; confirmation is a separate state.
        if valid_zones:
            zone = min(valid_zones, key=lambda z: abs(current-(float(z["low"])+float(z["high"]))/2))
            retest_rejected = _latest_retest_rejection(
                candles_by_tf["5m"], direction,
                float(zone["low"]), float(zone["high"])
            )
            latest_closed_time = candles_by_tf["5m"][-2]["time"]
            structure_break_on_retest = any(
                event.get("type") in ("BOS", "CHoCH")
                and event.get("direction") == direction
                and event.get("time") == latest_closed_time
                for event in analyses["5m"].get("events", [])
            )
            confirmation = (
                "confirmed_trigger"
                if retest_rejected and structure_break_on_retest
                else "retest_detected_waiting_structure"
                if retest_rejected
                else "developing"
                if (sweep or bos or choch or one_minute_shift)
                else "zone_waiting"
            )
            state = "watchlist" if score < min_quality else confirmation
            if confirmation == "confirmed_trigger" and score >= min_quality:
                state = "candidate_ready_for_risk_validation"
            scenarios.append({
                "direction": direction, "state": state, "quality_score": score,
                "score_breakdown": score_breakdown,
                "setup_class": "counter_trend" if counter else context,
                "zone": {"type": zone.get("type"), "low": float(zone["low"]),
                         "high": float(zone["high"]), "formed_at": zone.get("formed_at"),
                         "status": zone.get("status")},
                "current_price": current, "reasons": reasons,
                "confirmation": confirmation,
                "minimum_rr_requested": min_rr,
                "estimated_win_probability": None
            })
        else:
            scenarios.append({
                "direction": direction, "state": "watchlist" if score >= min_quality else "monitoring",
                "quality_score": score, "score_breakdown": score_breakdown,
                "setup_class": "counter_trend" if counter else context,
                "zone": None, "current_price": current, "reasons": reasons,
                "confirmation": "no_valid_5m_entry_zone",
                "minimum_rr_requested": min_rr,
                "estimated_win_probability": None
            })

    scenarios.sort(key=lambda x: x["quality_score"], reverse=True)
    return {
        "symbol": symbol, "primary_bias": primary, "higher_timeframe_context": context,
        "current_price_5m": current, "scenarios": scenarios,
        "best_scenario": scenarios[0] if scenarios else None,
        "estimated_win_probability": None,
        "probability_status": "requires_out_of_sample_backtest_and_calibration",
        "execution_allowed": False,
        "engine_version": "trade-intelligence-4.1",
        "note": "Scanner output is research/watchlist classification only. It does not place orders."
    }
