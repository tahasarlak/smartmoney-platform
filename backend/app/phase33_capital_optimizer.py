"""Phase 33: conservative position sizing advisory; never places orders."""
from __future__ import annotations
import math
from typing import Any

def optimize_capital(*, equity: float, max_portfolio_risk_pct: float,
                     current_open_risk: float, max_trade_risk_pct: float,
                     proposals: list[dict[str, Any]], max_positions: int,
                     current_positions: int = 0) -> dict[str, Any]:
    vals = (equity, max_portfolio_risk_pct, current_open_risk, max_trade_risk_pct)
    if not all(math.isfinite(float(x)) for x in vals): raise ValueError("Risk inputs must be finite")
    if equity <= 0 or not 0 <= max_portfolio_risk_pct <= 100 or current_open_risk < 0 or not 0 <= max_trade_risk_pct <= 100:
        raise ValueError("Invalid portfolio risk inputs")
    if not 1 <= int(max_positions) <= 100 or not 0 <= int(current_positions) <= max_positions:
        raise ValueError("Invalid position limits")
    if not isinstance(proposals, list) or len(proposals) > 100: raise ValueError("At most 100 proposals are allowed")
    portfolio_budget = equity * max_portfolio_risk_pct / 100
    remaining = max(0.0, portfolio_budget - current_open_risk)
    slots = max(0, max_positions - current_positions)
    output = []
    for p in proposals:
        if not isinstance(p, dict): raise ValueError("Each proposal must be an object")
        name = str(p.get("symbol") or "").upper()
        try:
            entry, stop = float(p["entry_price"]), float(p["stop_loss"])
            confidence = float(p.get("quality_score", 50))
            correlation = float(p.get("correlation_penalty", 0))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError(f"{name or 'proposal'}: invalid numeric fields")
        if not name or not all(math.isfinite(x) for x in (entry, stop, confidence, correlation)):
            raise ValueError("Proposal values must be finite and symbol required")
        if entry <= 0 or stop <= 0 or entry == stop or not 0 <= confidence <= 100 or not 0 <= correlation <= 1:
            raise ValueError(f"{name}: invalid entry, stop, quality or correlation")
        risk_per_unit = abs(entry - stop)
        desired_pct = min(max_trade_risk_pct, max_trade_risk_pct * confidence / 100)
        desired_cash = equity * desired_pct / 100 * (1 - correlation)
        allowed_cash = min(desired_cash, remaining) if slots > 0 else 0.0
        quantity = allowed_cash / risk_per_unit
        output.append({"symbol": name, "entry_price": entry, "stop_loss": stop,
                       "risk_cash": round(allowed_cash, 8), "risk_pct_of_equity": round(allowed_cash / equity * 100, 6),
                       "suggested_quantity": round(quantity, 10), "correlation_penalty": correlation,
                       "eligible_for_consideration": allowed_cash > 0 and confidence >= 50 and slots > 0})
        remaining -= allowed_cash
        if allowed_cash > 0: slots -= 1
    return {"equity": equity, "portfolio_risk_budget": round(portfolio_budget, 8),
            "current_open_risk": current_open_risk, "remaining_risk_budget": round(max(0, remaining), 8),
            "remaining_position_slots": slots, "proposals": output, "allocation_committed": False,
            "execution_allowed": False,
            "limitations": ["Advisory sizing only; exchange lot size, tick size, margin, fees and liquidity must be checked before execution.",
                            "Correlation penalty is caller-supplied and is not calculated from live returns.",
                            "No funds are reserved and no order is submitted."]}
