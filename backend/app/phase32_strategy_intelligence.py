"""TRADF Phase 32: explainable, non-executing strategy/regime evaluation."""
from __future__ import annotations

import math
from typing import Any

VALID_REGIMES = {"trending", "ranging", "transition", "high_volatility", "unknown"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return n if math.isfinite(n) else default


def evaluate_strategy_candidates(
    *,
    market_regime: str,
    strategies: list[dict[str, Any]],
    minimum_trades: int = 30,
    max_drawdown_pct: float = 15.0,
) -> dict[str, Any]:
    """Rank supplied strategy evidence; never places orders or changes allocations.

    Inputs are caller-supplied evidence. The output is analytical guidance only.
    """
    regime = str(market_regime or "unknown").strip().lower()
    if regime not in VALID_REGIMES:
        raise ValueError(f"market_regime must be one of: {', '.join(sorted(VALID_REGIMES))}")
    if isinstance(minimum_trades, bool) or not 5 <= int(minimum_trades) <= 10000:
        raise ValueError("minimum_trades must be between 5 and 10000")
    if not math.isfinite(float(max_drawdown_pct)) or not 0.1 <= float(max_drawdown_pct) <= 100:
        raise ValueError("max_drawdown_pct must be between 0.1 and 100")
    if not isinstance(strategies, list) or len(strategies) > 100:
        raise ValueError("strategies must be a list containing at most 100 candidates")

    scored: list[dict[str, Any]] = []
    for raw in strategies:
        if not isinstance(raw, dict):
            raise ValueError("each strategy must be an object")
        name = str(raw.get("name") or "").strip()
        if not name or len(name) > 100:
            raise ValueError("each strategy requires a name of 1 to 100 characters")
        trades_raw = raw.get("trade_count", 0)
        try:
            trade_count = int(trades_raw)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{name}: trade_count must be an integer")
        if isinstance(trades_raw, bool) or trade_count < 0:
            raise ValueError(f"{name}: trade_count must be a non-negative integer")

        win_rate = _num(raw.get("win_rate_pct"), float("nan"))
        profit_factor = _num(raw.get("profit_factor"), float("nan"))
        drawdown = _num(raw.get("max_drawdown_pct"), float("nan"))
        expectancy = _num(raw.get("expectancy_r"), float("nan"))
        if not all(math.isfinite(x) for x in (win_rate, profit_factor, drawdown, expectancy)):
            raise ValueError(f"{name}: all performance metrics must be finite numbers")
        if not 0 <= win_rate <= 100 or profit_factor < 0 or not 0 <= drawdown <= 100:
            raise ValueError(f"{name}: metric outside permitted range")

        issues: list[str] = []
        if trade_count < minimum_trades:
            issues.append("sample_below_minimum")
        if drawdown > max_drawdown_pct:
            issues.append("drawdown_above_limit")
        if profit_factor <= 1.0:
            issues.append("profit_factor_not_above_1")
        if expectancy <= 0:
            issues.append("non_positive_expectancy")
        if regime in {"transition", "high_volatility", "unknown"}:
            issues.append("regime_not_suitable_for_automatic_selection")

        # Transparent score: capped components, not a probability or forecast.
        sample_component = min(1.0, trade_count / max(1, minimum_trades * 3)) * 20.0
        pf_component = min(2.0, max(0.0, profit_factor - 1.0)) / 2.0 * 30.0
        expectancy_component = min(2.0, max(0.0, expectancy)) / 2.0 * 25.0
        drawdown_component = max(0.0, 1.0 - drawdown / max_drawdown_pct) * 25.0
        score = round(sample_component + pf_component + expectancy_component + drawdown_component, 2)

        # Regime compatibility is deliberately conservative and based on explicit labels.
        labels = {str(x).strip().lower() for x in raw.get("suitable_regimes", []) if str(x).strip()}
        compatible = regime in labels if regime in {"trending", "ranging"} else False
        if regime in {"trending", "ranging"} and not compatible:
            issues.append("regime_compatibility_not_provided")
        eligible = (
            trade_count >= minimum_trades
            and drawdown <= max_drawdown_pct
            and profit_factor > 1.0
            and expectancy > 0
            and regime in {"trending", "ranging"}
            and compatible
        )
        scored.append({
            "name": name,
            "score": score,
            "eligible_for_consideration": eligible,
            "regime_compatible": compatible,
            "trade_count": trade_count,
            "win_rate_pct": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "max_drawdown_pct": round(drawdown, 4),
            "expectancy_r": round(expectancy, 4),
            "issues": sorted(set(issues)),
        })

    scored.sort(key=lambda item: (item["eligible_for_consideration"], item["score"], item["trade_count"]), reverse=True)
    eligible_count = sum(1 for item in scored if item["eligible_for_consideration"])
    return {
        "status": "evaluated" if scored else "no_candidates",
        "market_regime": regime,
        "candidate_count": len(scored),
        "eligible_candidate_count": eligible_count,
        "minimum_trades": int(minimum_trades),
        "max_drawdown_pct": float(max_drawdown_pct),
        "ranked_strategies": scored,
        "selection": None,
        "allocation_changes": [],
        "execution_allowed": False,
        "method": "transparent_heuristic_score_not_predictive_probability",
        "limitations": [
            "Metrics and suitable_regimes are supplied by the caller and are not independently verified against the trade journal.",
            "The score is a transparent heuristic, not a probability, return forecast, or proof of future performance.",
            "Regime compatibility is considered only when an explicit suitable_regimes label is supplied.",
            "No strategy is automatically selected, enabled, disabled, or allocated capital.",
            "This endpoint does not place exchange orders.",
        ],
    }
