from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from .live_strategy_pipeline import evaluate_live_smc
from .market_data import binance_klines
from .live_signal_monitor import live_signal_monitor

router = APIRouter(prefix="/api/v1/intelligence", tags=["live-strategy"])


@router.get("/live-smc/{symbol}")
async def live_smc_evaluation(
    symbol: str,
    limit: int = Query(default=500, ge=100, le=1000),
    min_quality_score: int = Query(default=65, ge=0, le=100),
    min_rr: float = Query(default=2.0, ge=0.5, le=10.0),
    risk_percent: float = Query(default=0.5, gt=0, le=2.0),
    use_regime_filter: bool = True,
):
    normalized = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
        raise HTTPException(status_code=422, detail="Invalid symbol")
    try:
        return await evaluate_live_smc(
            normalized,
            binance_klines,
            limit=limit,
            min_quality_score=min_quality_score,
            min_rr=min_rr,
            risk_percent=risk_percent,
            use_regime_filter=use_regime_filter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Live SMC evaluation failed: {type(exc).__name__}: {exc}",
        )


@router.get("/live-signal-monitor/status")
def live_signal_monitor_status():
    """Read-only operational status for the automatic SMC signal journal monitor."""
    return live_signal_monitor.status()
