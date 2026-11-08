from __future__ import annotations

from typing import Any

from .market_regime import analyze_market_regime

_ALLOWED_TIMEFRAMES = ("4h", "1h", "15m", "5m")


def analyze_market_regime_intelligence(
    candles_by_tf: dict[str, list[dict[str, Any]]],
    *,
    min_trend_alignment: int = 2,
    high_volatility_ratio: float = 1.5,
    low_volatility_ratio: float = 0.75,
) -> dict[str, Any]:
    """Combine closed-candle regime classifications into an explainable context.

    The underlying analyzer treats the final row as forming. This layer does not
    predict returns, estimate win probability, or place orders.
    """
    if not isinstance(candles_by_tf, dict) or not candles_by_tf:
        raise ValueError("candles_by_tf must not be empty")
    if not isinstance(min_trend_alignment, int) or not 1 <= min_trend_alignment <= 4:
        raise ValueError("min_trend_alignment must be between 1 and 4")
    if not 1.0 <= float(high_volatility_ratio) <= 5.0:
        raise ValueError("high_volatility_ratio must be between 1 and 5")
    if not 0.1 <= float(low_volatility_ratio) < 1.0:
        raise ValueError("low_volatility_ratio must be between 0.1 and 1")

    unknown = set(candles_by_tf) - set(_ALLOWED_TIMEFRAMES)
    if unknown:
        raise ValueError(f"Unsupported timeframes: {', '.join(sorted(unknown))}")

    reports: dict[str, dict[str, Any]] = {}
    for timeframe in _ALLOWED_TIMEFRAMES:
        if timeframe not in candles_by_tf:
            continue
        reports[timeframe] = analyze_market_regime(
            candles_by_tf[timeframe],
            timeframe,
        )

    if not reports:
        raise ValueError("At least one supported timeframe is required")

    trend_reports = [
        report for report in reports.values()
        if report["regime"] == "trending"
    ]
    bullish = sum(r["trend_direction"] == "bullish" for r in trend_reports)
    bearish = sum(r["trend_direction"] == "bearish" for r in trend_reports)
    trend_count = len(trend_reports)

    if bullish > bearish:
        dominant_direction = "bullish"
        aligned_count = bullish
    elif bearish > bullish:
        dominant_direction = "bearish"
        aligned_count = bearish
    else:
        dominant_direction = "neutral"
        aligned_count = 0

    if trend_count == 0:
        aggregate_regime = (
            "ranging"
            if all(r["regime"] == "ranging" for r in reports.values())
            else "transition"
        )
    elif aligned_count >= min_trend_alignment and aligned_count == trend_count:
        aggregate_regime = "trending"
    elif aligned_count >= min_trend_alignment:
        aggregate_regime = "mixed_trend"
    else:
        aggregate_regime = "transition"

    volatility_ratios = [
        float(r["volatility_ratio_to_baseline"])
        for r in reports.values()
    ]
    max_volatility_ratio = max(volatility_ratios)
    min_volatility_ratio = min(volatility_ratios)
    if max_volatility_ratio >= high_volatility_ratio:
        volatility_state = "high_volatility"
    elif all(value <= low_volatility_ratio for value in volatility_ratios):
        volatility_state = "low_volatility"
    else:
        volatility_state = "normal_volatility"

    if aggregate_regime == "trending":
        strategy_bias = "trend_following"
        score_adjustment = 5
    elif aggregate_regime == "ranging":
        strategy_bias = "range_aware_reduced_frequency"
        score_adjustment = -5
    elif aggregate_regime == "mixed_trend":
        strategy_bias = "wait_for_timeframe_alignment"
        score_adjustment = -5
    else:
        strategy_bias = "selective_or_wait"
        score_adjustment = -10

    if volatility_state == "high_volatility":
        score_adjustment -= 5
        volatility_action = "reduce_risk_or_wait"
    elif volatility_state == "low_volatility":
        volatility_action = "watch_for_expansion"
    else:
        volatility_action = "normal_risk_controls"

    return {
        "status": "completed",
        "aggregate_regime": aggregate_regime,
        "dominant_direction": dominant_direction,
        "trend_alignment_count": aligned_count,
        "trending_timeframe_count": trend_count,
        "timeframe_count": len(reports),
        "volatility_state": volatility_state,
        "volatility_ratio_range": {
            "minimum": round(min_volatility_ratio, 4),
            "maximum": round(max_volatility_ratio, 4),
        },
        "strategy_policy": {
            "bias": strategy_bias,
            "quality_score_adjustment": score_adjustment,
            "volatility_action": volatility_action,
            "is_trade_permission": False,
            "note": (
                "Contextual guidance only. This policy does not authorize or "
                "reject execution and is not calibrated to profitability."
            ),
        },
        "timeframe_reports": reports,
        "methodology": {
            "type": "multi_timeframe_rule_based_aggregation",
            "source": "closed_candle_market_regime_analyzer",
            "prediction": False,
            "estimated_win_probability": None,
        },
        "execution_allowed": False,
    }
