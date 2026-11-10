from __future__ import annotations
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .v11_platform import current_user
from .forex_paper import start_forex_paper_run, forex_paper_status, stop_forex_paper_run, forex_worker_state

router = APIRouter(prefix="/api/v1/forex", tags=["forex-intraday-paper"])


class ForexPaperStartRequest(BaseModel):
    portfolio_id: str = Field(min_length=1, max_length=36)
    risk_per_trade_pct: float = Field(default=0.25, gt=0, le=2)
    min_quality_score: int = Field(default=65, ge=0, le=100)
    min_rr: float = Field(default=2.0, ge=0.5, le=10)
    commission_pct: float = Field(default=0.0, ge=0, le=1)
    spread_bps: float = Field(default=1.5, ge=0, le=500)
    slippage_bps: float = Field(default=0.5, ge=0, le=500)
    confirm_paper_only: bool = False


@router.get("/intraday/status")
def forex_intraday_status():
    return {
        "provider": "Twelve Data price WebSocket",
        "configured": bool(os.getenv("TWELVE_DATA_API_KEY", "").strip()),
        "websocket_enabled": bool(os.getenv("TWELVE_DATA_API_KEY", "").strip()),
        "worker": forex_worker_state(),
        "symbols": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD"],
        "timeframes": ["1m", "5m", "15m", "1h", "4h"],
        "execution_allowed": False,
        "warning": "Free-plan WebSocket is limited to trial symbols. Confirm all eight subscriptions in worker logs before starting a paper run.",
    }


@router.post("/paper/start", status_code=201)
def api_start_forex_paper(payload: ForexPaperStartRequest, user=Depends(current_user)):
    try:
        return start_forex_paper_run(
            user_id=user["id"], portfolio_id=payload.portfolio_id,
            risk_per_trade_pct=payload.risk_per_trade_pct,
            min_quality_score=payload.min_quality_score, min_rr=payload.min_rr,
            commission_pct=payload.commission_pct, spread_bps=payload.spread_bps,
            slippage_bps=payload.slippage_bps,
            confirm_paper_only=payload.confirm_paper_only,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/paper/status")
def api_forex_paper_status(portfolio_id: str, user=Depends(current_user)):
    try:
        return forex_paper_status(user["id"], portfolio_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/paper/{run_id}/stop")
def api_stop_forex_paper(run_id: str, user=Depends(current_user)):
    try:
        return stop_forex_paper_run(user["id"], run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
