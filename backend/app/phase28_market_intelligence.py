"""Phase 28: multi-timeframe market context from supplied OHLC candles."""
from __future__ import annotations
from typing import Any
from .market_regime import analyze_market_regime

_ALLOWED_TIMEFRAMES = {"4h", "1h", "15m", "5m", "1m"}

def build_market_intelligence(*, symbol: str,
                              candles_by_timeframe: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    normalized = str(symbol).strip().upper()
    if not normalized or len(normalized) > 40 or not normalized.replace("_", "").isalnum():
        raise ValueError("Invalid symbol")
    if not isinstance(candles_by_timeframe, dict) or not 1 <= len(candles_by_timeframe) <= 5:
        raise ValueError("Provide candles for 1..5 timeframes")
    unknown = sorted(set(candles_by_timeframe) - _ALLOWED_TIMEFRAMES)
    if unknown:
        raise ValueError(f"Unsupported timeframes: {', '.join(unknown)}")
    reports = {}
    for timeframe, candles in candles_by_timeframe.items():
        reports[timeframe] = analyze_market_regime(candles, timeframe)
    trend_directions = [r["trend_direction"] for r in reports.values()
                        if r["regime"] == "trending" and r["trend_direction"] in {"bullish", "bearish"}]
    consensus = "mixed"
    if trend_directions and len(set(trend_directions)) == 1:
        consensus = trend_directions[0]
    elif not trend_directions:
        consensus = "no_confirmed_trend"
    expanded = [tf for tf, report in reports.items()
                if report["volatility_regime"] == "expanded"]
    transition = [tf for tf, report in reports.items()
                  if report["regime"] == "transition"]
    return {
        "status": "completed", "symbol": normalized, "timeframes": reports,
        "trend_consensus": consensus,
        "expanded_volatility_timeframes": expanded,
        "transition_timeframes": transition,
        "alignment_ratio": round(
            max(trend_directions.count("bullish"), trend_directions.count("bearish")) /
            len(trend_directions), 4
        ) if trend_directions else None,
        "execution_allowed": False,
        "method": "existing_closed_candle_market_regime_classifier",
        "limitations": ["Contextual classification only; no win-probability or entry signal is generated.",
                        "Input candle freshness and provider provenance must be validated by the caller."],
    }
