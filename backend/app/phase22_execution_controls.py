"""Phase 22: conservative paper-execution preflight controls."""
from __future__ import annotations
import math
from typing import Any

def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} must be numeric") from None
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result

def build_execution_preflight(*, portfolio: dict[str, Any], trades: list[dict[str, Any]],
                              side: str, quantity: float, entry: float, stop_loss: float) -> dict[str, Any]:
    side = str(side).lower()
    if side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    qty = _number(quantity, "quantity")
    entry_value = _number(entry, "entry")
    stop = _number(stop_loss, "stop_loss")
    if qty <= 0 or entry_value <= 0 or stop <= 0:
        raise ValueError("quantity, entry and stop_loss must be positive")
    if (side == "long" and stop >= entry_value) or (side == "short" and stop <= entry_value):
        raise ValueError("stop_loss must be below entry for long and above entry for short")
    equity = _number(portfolio.get("cash_equity", portfolio.get("initial_equity", 0)), "cash_equity")
    if equity <= 0:
        raise ValueError("portfolio equity must be positive")
    proposed_risk = abs(entry_value - stop) * qty
    proposed_risk_pct = proposed_risk / equity * 100.0
    current_risk_cash = max(0.0, _number(portfolio.get("open_risk_cash", 0), "open_risk_cash"))
    current_risk_pct = current_risk_cash / equity * 100.0
    active = [t for t in trades if t.get("status") in {"pending_entry", "open", "partially_closed"}
              and float(t.get("remaining_quantity", 0) or 0) > 0]
    max_open = int(portfolio.get("max_open_trades", 0) or 0)
    max_trade_pct = _number(portfolio.get("max_trade_risk_pct", 0), "max_trade_risk_pct")
    max_portfolio_pct = _number(portfolio.get("max_portfolio_risk_pct", 0), "max_portfolio_risk_pct")
    reasons: list[str] = []
    if max_open > 0 and len(active) >= max_open:
        reasons.append("max_open_trades_reached")
    if max_trade_pct > 0 and proposed_risk_pct > max_trade_pct + 1e-9:
        reasons.append("single_trade_risk_limit_exceeded")
    if max_portfolio_pct > 0 and current_risk_pct + proposed_risk_pct > max_portfolio_pct + 1e-9:
        reasons.append("portfolio_risk_limit_exceeded")
    return {
        "status": "rejected" if reasons else "passed",
        "proposed_risk_cash": round(proposed_risk, 8),
        "proposed_risk_pct": round(proposed_risk_pct, 6),
        "current_open_risk_pct": round(current_risk_pct, 6),
        "projected_open_risk_pct": round(current_risk_pct + proposed_risk_pct, 6),
        "active_trade_count": len(active), "max_open_trades": max_open,
        "max_trade_risk_pct": max_trade_pct, "max_portfolio_risk_pct": max_portfolio_pct,
        "rejection_reasons": reasons, "mode": "paper_preflight",
        "execution_allowed": False,
        "limitations": ["Preflight is advisory and does not reserve capital or create an order.",
                        "Legacy PaperOrder exposure may be represented in portfolio.open_risk_cash but is not counted as an ExecutionTrade here."]
    }
