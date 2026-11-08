"""Phase 23: deterministic, conservative adaptive risk recommendation."""
from __future__ import annotations
import math
from typing import Any

def recommend_adaptive_risk(*, baseline_risk_pct: float = 0.25, max_risk_pct: float = 0.5,
                            volatility_multiple: float = 1.0, drawdown_pct: float = 0.0,
                            market_regime: str = "unknown") -> dict[str, Any]:
    values = [baseline_risk_pct, max_risk_pct, volatility_multiple, drawdown_pct]
    try:
        baseline, cap, vol, dd = [float(x) for x in values]
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Risk inputs must be numeric") from None
    if not all(math.isfinite(x) for x in (baseline, cap, vol, dd)):
        raise ValueError("Risk inputs must be finite")
    if baseline <= 0 or cap <= 0 or vol <= 0 or dd < 0 or baseline > 5 or cap > 5:
        raise ValueError("Invalid risk inputs")
    regime = str(market_regime).lower().strip()
    known = {"trending", "transition", "high_volatility", "ranging", "unknown"}
    if regime not in known:
        raise ValueError("market_regime must be trending, transition, high_volatility, ranging or unknown")
    volatility_factor = min(1.0, max(0.2, 1.0 / vol))
    drawdown_factor = 1.0 if dd < 2 else (0.75 if dd < 5 else (0.4 if dd < 8 else 0.0))
    regime_factor = {"trending": 1.0, "ranging": 0.8, "transition": 0.6,
                     "high_volatility": 0.4, "unknown": 0.7}[regime]
    recommended = min(cap, baseline * volatility_factor * drawdown_factor * regime_factor)
    pause = dd >= 8 or vol >= 3 or recommended < baseline * 0.05
    if pause:
        recommended = 0.0
    return {
        "status": "pause_recommended" if pause else "recommendation_ready",
        "baseline_risk_pct": round(baseline, 6), "recommended_risk_pct": round(recommended, 6),
        "max_risk_pct": round(cap, 6), "volatility_multiple": round(vol, 6),
        "volatility_factor": round(volatility_factor, 6), "drawdown_pct": round(dd, 6),
        "drawdown_factor": round(drawdown_factor, 6), "market_regime": regime,
        "regime_factor": regime_factor, "execution_allowed": False,
        "limitations": ["Heuristic recommendation only; it does not alter portfolio settings or orders.",
                        "Volatility multiple and drawdown must be supplied from a validated measurement process."]
    }
