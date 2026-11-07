from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

class Candle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0

class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_basis: Literal["balance", "equity"] = "equity"
    risk_per_trade_pct: float = Field(0.5, ge=0.05, le=2.0)
    min_rr: float = Field(2.0, ge=0.5, le=10)
    min_quality_score: int = Field(50, ge=0, le=100)
    max_daily_loss_pct: float = Field(3, ge=0.1, le=20)
    max_weekly_loss_pct: float = Field(6, ge=0.1, le=40)
    max_monthly_loss_pct: float = Field(10, ge=0.1, le=60)
    max_drawdown_pct: float = Field(15, ge=1, le=80)
    max_open_trades: int = Field(3, ge=1, le=50)
    max_total_open_risk_pct: float = Field(3, ge=0.1, le=20)
    allow_counter_trend: bool = True
    auto_trading_enabled: bool = False
    mode: Literal["conservative", "balanced", "active", "custom"] = "balanced"

class OHLCVRequest(BaseModel):
    symbol: str = Field("BTCUSDT", pattern=r"^[A-Z0-9]{5,20}$")
    interval: Literal["1m","3m","5m","15m","30m","1h","2h","4h","6h","12h","1d","1w"] = "15m"
    limit: int = Field(300, ge=50, le=1000)

class AnalysisRequest(BaseModel):
    symbol: str
    candles: list[Candle] = Field(min_length=50, max_length=5000)
    swing_length: int = Field(3, ge=2, le=10)
    equal_level_tolerance_pct: float = Field(0.05, ge=0.001, le=1.0)

class PositionSizeRequest(BaseModel):
    account_value: float = Field(gt=0)
    risk_pct: float = Field(gt=0, le=2)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    # Cash loss per 1.0 price move for one unit of position. Must come from
    # the broker/exchange contract specification and account-currency conversion.
    cash_per_price_unit_per_lot: float = Field(gt=0)
    lot_step: float = Field(gt=0, default=0.01)
    min_lot: float = Field(gt=0, default=0.01)
    max_lot: float = Field(gt=0, default=100)

class PaperOrderRequest(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0)
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
