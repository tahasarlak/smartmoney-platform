from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class RiskPreflightRequest(BaseModel):
    balance: float = Field(gt=0)
    equity: float = Field(gt=0)
    day_start_equity: float = Field(gt=0)
    week_start_equity: float = Field(gt=0)
    month_start_equity: float = Field(gt=0)
    peak_equity: float = Field(gt=0)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    quantity: float = Field(gt=0)
    open_trades: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    counter_trend: bool = False
    correlation_group: str | None = Field(default=None, max_length=64)


class BacktestSignal(BaseModel):
    index: int = Field(ge=0)
    direction: Literal["bullish", "bearish"]
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    quantity: float = Field(default=1.0, gt=0)
    symbol: str | None = None


class BacktestRequest(BaseModel):
    candles: list[dict[str, Any]] = Field(min_length=3, max_length=100000)
    signals: list[BacktestSignal] = Field(default_factory=list, max_length=10000)
    initial_equity: float = Field(default=10000, gt=0)
    spread: float = Field(default=0, ge=0)
    slippage: float = Field(default=0, ge=0)
    commission_pct: float = Field(default=0, ge=0, le=5)
    max_open_trades: int = Field(default=3, ge=1, le=100)
    max_daily_loss_pct: float = Field(default=3, ge=0, le=100)
    max_weekly_loss_pct: float = Field(default=6, ge=0, le=100)
    max_drawdown_pct: float = Field(default=15, ge=0, le=100)

class MultiSymbolBacktestSignal(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    index: int = Field(ge=0)
    direction: Literal["bullish", "bearish"]
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    quantity: float = Field(default=1.0, gt=0)


class MultiSymbolBacktestRequest(BaseModel):
    candles_by_symbol: dict[str, list[dict[str, Any]]] = Field(
        min_length=1,
        max_length=30
    )
    signals: list[MultiSymbolBacktestSignal] = Field(
        default_factory=list,
        max_length=10000
    )
    initial_equity: float = Field(default=10000, gt=0)
    spread: float = Field(default=0, ge=0)
    slippage: float = Field(default=0, ge=0)
    commission_pct: float = Field(default=0, ge=0, le=5)
    max_open_trades: int = Field(default=3, ge=1, le=100)
    max_daily_loss_pct: float = Field(default=3, ge=0, le=100)
    max_weekly_loss_pct: float = Field(default=6, ge=0, le=100)
    max_drawdown_pct: float = Field(default=15, ge=0, le=100)
