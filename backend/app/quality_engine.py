from __future__ import annotations

from typing import Any


QUALITY_METHODOLOGY_VERSION = "signal-quality-1.0"


def _structure(analyses: dict[str, dict[str, Any]], timeframe: str) -> str:
    value = str((analyses.get(timeframe) or {}).get("structure", "range")).lower()
    return value if value in ("bullish", "bearish") else "range"


def _has_event(
    analyses: dict[str, dict[str, Any]],
    timeframe: str,
    event_types: set[str],
    direction: str,
) -> bool:
    events = (analyses.get(timeframe) or {}).get("events", [])
    return any(
        isinstance(event, dict)
        and str(event.get("type", "")).upper() in event_types
        and event.get("direction") == direction
        for event in events
    )


def assess_signal_quality(
    *,
    direction: str,
    technical_score: int,
    analyses: dict[str, dict[str, Any]],
    regimes: dict[str, dict[str, Any]] | None = None,
    zone_valid: bool = False,
    confirmation: str = "unknown",
    counter_trend: bool = False,
    min_quality_score: int = 50,
) -> dict[str, Any]:
    """Add independent confluence and market-regime evidence to the rule-based score.

    This is a deterministic research-quality assessment, not a probability model.
    All upstream structure/regime inputs must be calculated from closed candles.
    """
    if direction not in ("bullish", "bearish"):
        raise ValueError("direction must be bullish or bearish")
    if not isinstance(technical_score, int) or not 0 <= technical_score <= 100:
        raise ValueError("technical_score must be an integer from 0 to 100")
    if not 0 <= min_quality_score <= 100:
        raise ValueError("min_quality_score must be between 0 and 100")

    regimes = regimes or {}
    components: dict[str, int] = {"technical_evidence": technical_score}
    evidence: list[dict[str, str]] = []
    flags: list[str] = []
    groups: set[str] = set()

    # Multi-timeframe trend agreement is counted as one evidence family.
    aligned = [tf for tf in ("4h", "1h", "15m", "5m", "1m")
               if _structure(analyses, tf) == direction]
    opposing = [tf for tf in ("4h", "1h", "15m")
                if _structure(analyses, tf) in ("bullish", "bearish")
                and _structure(analyses, tf) != direction]
    if aligned:
        groups.add("multi_timeframe_structure")
        evidence.append({
            "group": "multi_timeframe_structure",
            "detail": "Directional structure agrees on " + ", ".join(aligned),
        })
    if len(opposing) >= 2 and len(aligned) <= 1:
        flags.append("multi_timeframe_conflict")
    if counter_trend:
        flags.append("counter_trend_setup")

    if _has_event(analyses, "15m", {"LIQUIDITY_SWEEP"}, direction):
        groups.add("liquidity")
        evidence.append({"group": "liquidity", "detail": "15M liquidity sweep supports the setup"})

    if _has_event(analyses, "5m", {"BOS", "CHOCH"}, direction):
        groups.add("structure_shift")
        evidence.append({"group": "structure_shift", "detail": "5M BOS/CHoCH supports the direction"})

    if _has_event(analyses, "1m", {"CHOCH"}, direction):
        groups.add("micro_confirmation")
        evidence.append({"group": "micro_confirmation", "detail": "1M CHoCH supports the direction"})

    if zone_valid:
        groups.add("entry_location")
        evidence.append({"group": "entry_location", "detail": "A valid 5M entry zone is available"})
    else:
        flags.append("no_valid_entry_zone")

    if confirmation == "confirmed_trigger":
        groups.add("closed_candle_trigger")
        evidence.append({"group": "closed_candle_trigger", "detail": "Closed 5M retest rejection and same-candle structure break confirmed"})
    elif confirmation == "retest_detected_waiting_structure":
        groups.add("retest")
        evidence.append({"group": "retest", "detail": "Retest rejection detected; structure confirmation is still missing"})
        flags.append("structure_confirmation_missing")
    else:
        flags.append("entry_trigger_not_confirmed")

    adjustments = 0
    higher = regimes.get("4h") or {}
    mid = regimes.get("15m") or {}
    if higher.get("regime") == "trending":
        if higher.get("trend_direction") == direction:
            adjustments += 4
            components["4h_regime_alignment"] = 4
            groups.add("market_regime")
            evidence.append({"group": "market_regime", "detail": "4H market regime trend agrees"})
        elif higher.get("trend_direction") in ("bullish", "bearish"):
            adjustments -= 4
            components["4h_regime_conflict"] = -4
            flags.append("4h_regime_conflict")

    if mid.get("regime") == "trending":
        if mid.get("trend_direction") == direction:
            adjustments += 2
            components["15m_regime_alignment"] = 2
            groups.add("market_regime")
        elif mid.get("trend_direction") in ("bullish", "bearish"):
            adjustments -= 2
            components["15m_regime_conflict"] = -2
            flags.append("15m_regime_conflict")

    if higher.get("volatility_regime") == "expanded":
        adjustments -= 3
        components["expanded_volatility"] = -3
        flags.append("expanded_volatility")
    if mid.get("volume_participation") == "low":
        adjustments -= 2
        components["low_volume_participation"] = -2
        flags.append("low_volume_participation")

    final_score = max(0, min(100, technical_score + adjustments))
    grade = (
        "strong" if final_score >= 80 else
        "good" if final_score >= 65 else
        "moderate" if final_score >= 50 else
        "weak"
    )

    # A high numeric score alone never makes a setup review-ready.
    review_eligible = bool(
        zone_valid
        and confirmation == "confirmed_trigger"
        and final_score >= min_quality_score
    )
    if review_eligible:
        classification = "ready_for_review"
    elif zone_valid and final_score >= min_quality_score:
        classification = "watchlist_candidate"
    elif zone_valid:
        classification = "below_quality_threshold"
    else:
        classification = "monitoring"

    risk_count = len(flags)
    false_signal_risk = (
        "elevated" if "multi_timeframe_conflict" in flags
        or ("counter_trend_setup" in flags and "entry_trigger_not_confirmed" in flags)
        or risk_count >= 4 else
        "moderate" if risk_count >= 2 else
        "low"
    )

    return {
        "methodology_version": QUALITY_METHODOLOGY_VERSION,
        "quality_score": final_score,
        "grade": grade,
        "classification": classification,
        "review_eligible": review_eligible,
        "score_components": components,
        "independent_confluence_count": len(groups),
        "confluence_groups": sorted(groups),
        "supporting_evidence": evidence,
        "risk_flags": flags,
        "false_signal_risk": false_signal_risk,
        "estimated_win_probability": None,
        "probability_status": "not_a_probability_requires_out_of_sample_calibration",
        "closed_candle_evidence_required": True,
    }
