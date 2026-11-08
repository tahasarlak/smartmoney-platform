"""Phase 32: explainable strategy/regime ranking. Advisory only."""
from __future__ import annotations
import math
from typing import Any

REGIMES = {"trending", "ranging", "transition", "high_volatility", "unknown"}

def evaluate_strategy_candidates(*, market_regime: str, strategies: list[dict[str, Any]],
                                 minimum_trades: int = 30, max_drawdown_pct: float = 15.0) -> dict[str, Any]:
    regime = str(market_regime or "unknown").strip().lower()
    if regime not in REGIMES:
        raise ValueError("Unsupported market_regime")
    if isinstance(minimum_trades, bool) or not 5 <= int(minimum_trades) <= 10000:
        raise ValueError("minimum_trades must be between 5 and 10000")
    if not math.isfinite(float(max_drawdown_pct)) or not 0.1 <= float(max_drawdown_pct) <= 100:
        raise ValueError("max_drawdown_pct must be between 0.1 and 100")
    if not isinstance(strategies, list) or len(strategies) > 100:
        raise ValueError("strategies must contain at most 100 items")
    ranked = []
    for row in strategies:
        if not isinstance(row, dict):
            raise ValueError("Each strategy must be an object")
        name = str(row.get("name") or "").strip()
        if not name or len(name) > 100:
            raise ValueError("Strategy name is required (max 100 chars)")
        try:
            count = int(row.get("trade_count", 0))
            win = float(row.get("win_rate_pct", 0))
            pf = float(row.get("profit_factor", 0))
            dd = float(row.get("max_drawdown_pct", 0))
            exp = float(row.get("expectancy_r", 0))
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{name}: metrics must be numeric")
        if isinstance(row.get("trade_count"), bool) or count < 0:
            raise ValueError(f"{name}: invalid trade_count")
        if not all(math.isfinite(x) for x in (win, pf, dd, exp)):
            raise ValueError(f"{name}: metrics must be finite")
        if not 0 <= win <= 100 or pf < 0 or not 0 <= dd <= 100:
            raise ValueError(f"{name}: metric outside permitted range")
        labels = {str(x).strip().lower() for x in row.get("suitable_regimes", [])}
        compatible = regime in labels if regime in {"trending", "ranging"} else False
        issues = []
        if count < minimum_trades: issues.append("sample_below_minimum")
        if dd > max_drawdown_pct: issues.append("drawdown_above_limit")
        if pf <= 1: issues.append("profit_factor_not_above_1")
        if exp <= 0: issues.append("non_positive_expectancy")
        if regime not in {"trending", "ranging"}: issues.append("regime_not_suitable_for_selection")
        elif not compatible: issues.append("regime_compatibility_not_provided")
        score = (
            min(1, count / (minimum_trades * 3)) * 20
            + min(2, max(0, pf - 1)) / 2 * 30
            + min(2, max(0, exp)) / 2 * 25
            + max(0, 1 - dd / max_drawdown_pct) * 25
        )
        eligible = (count >= minimum_trades and dd <= max_drawdown_pct and pf > 1 and exp > 0
                    and regime in {"trending", "ranging"} and compatible)
        ranked.append({"name": name, "score": round(score, 2),
                       "eligible_for_consideration": eligible, "regime_compatible": compatible,
                       "trade_count": count, "win_rate_pct": win, "profit_factor": pf,
                       "max_drawdown_pct": dd, "expectancy_r": exp, "issues": issues})
    ranked.sort(key=lambda x: (x["eligible_for_consideration"], x["score"], x["trade_count"]), reverse=True)
    return {"status": "evaluated" if ranked else "no_candidates", "market_regime": regime,
            "candidate_count": len(ranked), "eligible_candidate_count": sum(x["eligible_for_consideration"] for x in ranked),
            "ranked_strategies": ranked, "selection": None, "execution_allowed": False,
            "method": "transparent_heuristic_not_predictive_probability",
            "limitations": ["Metrics are caller-supplied and are not independently verified against the trade journal.",
                            "A score is not a probability or return forecast.",
                            "No strategy is activated and no capital is allocated."]}
