"""Phase 34: deterministic order preflight. No exchange adapter or order submission."""
from __future__ import annotations
import math
from typing import Any

def execution_preflight(*, symbol: str, side: str, quantity: float, entry_price: float,
                        stop_loss: float, take_profit: float, equity: float,
                        current_open_risk: float, max_portfolio_risk_pct: float,
                        max_trade_risk_pct: float, max_open_trades: int,
                        current_open_trades: int, max_slippage_bps: float = 10,
                        estimated_slippage_bps: float = 0, fee_pct: float = 0.1,
                        min_notional: float = 5) -> dict[str, Any]:
    issues=[]
    symbol=str(symbol or "").strip().upper()
    if not symbol or len(symbol)>30 or not symbol.replace("_","").isalnum(): issues.append("invalid_symbol")
    if side not in {"long","short"}: issues.append("invalid_side")
    nums=(quantity,entry_price,stop_loss,take_profit,equity,current_open_risk,max_portfolio_risk_pct,
          max_trade_risk_pct,max_slippage_bps,estimated_slippage_bps,fee_pct,min_notional)
    if not all(math.isfinite(float(x)) for x in nums): raise ValueError("All numeric inputs must be finite")
    if any(x <= 0 for x in (quantity,entry_price,stop_loss,take_profit,equity)): issues.append("non_positive_order_value")
    if current_open_risk < 0 or not 0 <= max_portfolio_risk_pct <= 100 or not 0 <= max_trade_risk_pct <= 100: issues.append("invalid_risk_limits")
    if max_open_trades < 1 or current_open_trades < 0: issues.append("invalid_position_count")
    if current_open_trades >= max_open_trades: issues.append("max_open_trades_reached")
    if estimated_slippage_bps < 0 or max_slippage_bps < 0 or estimated_slippage_bps > max_slippage_bps: issues.append("slippage_limit_exceeded")
    if fee_pct < 0 or min_notional < 0: issues.append("invalid_cost_assumptions")
    if side == "long" and not stop_loss < entry_price < take_profit: issues.append("invalid_long_protective_levels")
    if side == "short" and not take_profit < entry_price < stop_loss: issues.append("invalid_short_protective_levels")
    notional=quantity*entry_price
    risk=quantity*abs(entry_price-stop_loss)
    risk_pct=risk/equity*100 if equity>0 else float("inf")
    if notional < min_notional: issues.append("below_minimum_notional")
    if risk_pct > max_trade_risk_pct + 1e-9: issues.append("trade_risk_limit_exceeded")
    if (current_open_risk+risk)/equity*100 > max_portfolio_risk_pct + 1e-9: issues.append("portfolio_risk_limit_exceeded")
    estimated_cost=notional*(fee_pct/100 + estimated_slippage_bps/10000)
    return {"status":"blocked" if issues else "preflight_passed","symbol":symbol,"side":side,
            "notional":round(notional,8),"gross_stop_risk":round(risk,8),"risk_pct_of_equity":round(risk_pct,6),
            "estimated_entry_cost":round(estimated_cost,8),"issues":sorted(set(issues)),
            "order_submitted":False,"execution_allowed":False,
            "note":"Preflight validation only. A passed result is not an exchange acceptance or permission to trade live."}
