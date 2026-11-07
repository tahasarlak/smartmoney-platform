from pydantic import BaseModel, Field
from typing import Literal

class SignalPriceUpdate(BaseModel):
    price: float = Field(gt=0)
    timestamp: str | None = None

class SignalListQuery(BaseModel):
    status: str | None = None
    symbol: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{5,20}$")
    limit: int = Field(default=100, ge=1, le=500)
