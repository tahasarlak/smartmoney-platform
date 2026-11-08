"""Phase 29: advisory strategy governance; never auto-enables strategies."""
from __future__ import annotations
import math
from typing import Any

def rank_strategy_candidates(*, strategies: list[dict[str, Any]],
                             market_regime: str = "unknown",
                             max_recommended: int = 5,
                             min_sample_size: int = 30) -> dict[str, Any]:
    if not isinstance(strategies, list) or not 1 <= len(strategies) <= 100:
        raise ValueError("Provide 1..100 strategies")
    if not 1 <= int(max_recommended) <= 20 or not 5 <= int(min_sample_size) <= 10000:
        raise ValueError("Invalid recommendation limits")
    regime = str(market_regime).strip().lower()
    if regime not in {"trending", "ranging", "transition", "high_volatility", "unknown"}:
        raise ValueError("Unsupported market_regime")
    rows, seen = [], set()
    for item in strategies:
        sid = str(item.get("strategy_id") or "").strip()
        if not sid or sid in seen:
            raise ValueError("Each strategy needs a unique strategy_id")
        seen.add(sid)
        try:
            sample = int(item.get("sample_size", 0))
            expectancy = float(item.get("out_of_sample_expectancy_r"))
            drawdown = float(item.get("max_drawdown_pct", 0))
            stability = float(item.get("stability_score", 0.5))
            correlation = float(item.get("crowding_score", 0))
        except (TypeError, ValueError):
            raise ValueError(f"Invalid numeric metrics for {sid}") from None
        if sample < 0 or not all(math.isfinite(x) for x in (expectancy, drawdown, stability, correlation)):
            raise ValueError(f"Non-finite metrics for {sid}")
        if not 0 <= drawdown <= 100 or not 0 <= stability <= 1 or not 0 <= correlation <= 1:
            raise ValueError(f"Metrics out of range for {sid}")
        compatible = item.get("market_regimes")
        regime_match = regime == "unknown" or not compatible or regime in compatible
        eligible = sample >= min_sample_size and expectancy > 0 and drawdown < 50 and regime_match
        score = (expectancy * 40) + (stability * 30) - (drawdown * 0.3) - (correlation * 20)
        rows.append({
            "strategy_id": sid, "sample_size": sample,
            "out_of_sample_expectancy_r": round(expectancy, 6),
            "max_drawdown_pct": round(drawdown, 5),
            "stability_score": round(stability, 4),
            "crowding_score": round(correlation, 4),
            "regime_compatible": regime_match, "eligible": eligible,
            "governance_score": round(score, 5),
            "recommendation": "candidate_for_paper_validation" if eligible else "insufficient_or_unfavorable_evidence",
        })
    rows.sort(key=lambda x: (-x["eligible"], -x["governance_score"], x["strategy_id"]))
    recommended = [r["strategy_id"] for r in rows if r["eligible"]][:max_recommended]
    return {
        "status": "completed", "market_regime": regime, "strategies": rows,
        "recommended_for_paper_validation": recommended,
        "auto_activation": False, "execution_allowed": False,
        "limitations": ["Advisory ranking only; input metrics are trusted as supplied and are not recalculated here.",
                        "No strategy is enabled, disabled, or allocated capital automatically."],
    }
