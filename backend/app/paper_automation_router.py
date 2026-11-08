from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from .paper_automation import (
    paper_automation_status,
    start_paper_automation,
    stop_paper_automation,
)
from .v11_platform import current_user

router = APIRouter(prefix="/api/v1/intelligence/paper-automation", tags=["paper-automation"])


class PaperAutomationStartRequest(BaseModel):
    portfolio_id: str = Field(min_length=1, max_length=36)
    account_id: str = Field(min_length=1, max_length=36)
    symbols: list[str] | None = Field(default=None, max_length=50)
    use_watchlist: bool = True
    risk_per_trade_pct: float = Field(default=0.25, gt=0, le=5)
    min_quality_score: int = Field(default=70, ge=0, le=100)
    commission_pct: float = Field(default=0.04, ge=0, le=1)
    slippage_bps: float = Field(default=2.0, ge=0, le=500)
    confirm_paper_only: bool = False

    @model_validator(mode="after")
    def require_explicit_paper_confirmation(self):
        if self.confirm_paper_only is not True:
            raise ValueError("Set confirm_paper_only=true to start paper automation")
        if not self.use_watchlist and not self.symbols:
            raise ValueError("Provide symbols when use_watchlist=false")
        return self


@router.post("/start", status_code=201)
def api_start_paper_automation(payload: PaperAutomationStartRequest, user=Depends(current_user)):
    try:
        return start_paper_automation(
            user_id=user["id"],
            portfolio_id=payload.portfolio_id,
            account_id=payload.account_id,
            symbols=payload.symbols,
            use_watchlist=payload.use_watchlist,
            risk_per_trade_pct=payload.risk_per_trade_pct,
            min_quality_score=payload.min_quality_score,
            commission_pct=payload.commission_pct,
            slippage_bps=payload.slippage_bps,
            confirm_paper_only=payload.confirm_paper_only,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/status")
def api_paper_automation_status(portfolio_id: str, user=Depends(current_user)):
    try:
        return paper_automation_status(user["id"], portfolio_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{run_id}/stop")
def api_stop_paper_automation(run_id: str, user=Depends(current_user)):
    try:
        return stop_paper_automation(user["id"], run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
