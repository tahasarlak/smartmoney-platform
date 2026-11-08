from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from .phase12_research import run_phase12_research_suite

router = APIRouter(prefix="/api/v1/intelligence/phase12", tags=["phase12-strategy-intelligence"])


@router.get("/capabilities")
def phase12_capabilities():
    return {
        "phase": "12",
        "name": "Strategy Validation & Trading Intelligence",
        "capabilities": [
            "multi_strategy_walk_forward_comparison",
            "entry_regime_performance_attribution",
            "risk_sensitivity_scenarios",
            "portfolio_risk_allocation",
            "historical_return_correlation",
            "forward_testing_trade_analytics",
            "buy_and_hold_context_benchmark",
            "final_strategy_evidence_audit",
        ],
        "database_required": False,
        "live_market_connection_required": False,
        "execution_allowed": False,
    }


@router.post("/evaluate")
def evaluate_phase12(payload: dict[str, Any] = Body(...)):
    try:
        return run_phase12_research_suite(payload)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
