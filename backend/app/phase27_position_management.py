"""Phase 27: read-only position-management suggestions."""
from __future__ import annotations
import math
from typing import Any

def build_position_guidance(*, trades: list[dict[str, Any]],
                            prices_by_trade_id: dict[str, float],
                            near_level_pct: float = 0.5) -> dict[str, Any]:
    if not math.isfinite(float(near_level_pct)) or not 0 < near_level_pct <= 10:
        raise ValueError("near_level_pct must be greater than 0 and at most 10")
    items = []
    for trade in trades:
        tid = str(trade.get("id") or "")
        status = str(trade.get("status") or "")
        if status not in {"pending_entry", "open", "partially_closed"}:
            continue
        raw_price = prices_by_trade_id.get(tid, trade.get("last_price"))
        if raw_price is None:
            items.append({"trade_id": tid, "symbol": trade.get("symbol"),
                          "status": "price_unavailable", "suggestions": ["Wait for a valid persisted market price."]})
            continue
        price = float(raw_price)
        side = str(trade.get("side") or "").lower()
        if not math.isfinite(price) or price <= 0 or side not in {"long", "short"}:
            raise ValueError(f"Invalid price or side for trade {tid}")
        entry = float(trade.get("avg_entry_price") or trade.get("planned_entry") or 0)
        stop = float(trade.get("stop_loss") or 0)
        target = float(trade.get("tp1") or 0)
        if entry <= 0 or stop <= 0:
            raise ValueError(f"Trade {tid} has invalid entry or stop")
        risk = abs(entry - float(trade.get("initial_stop_loss") or stop))
        signed_move = (price - entry) if side == "long" else (entry - price)
        r_multiple = signed_move / risk if risk > 0 else None
        stop_distance = abs(price - stop) / price * 100
        target_distance = abs(target - price) / price * 100 if target > 0 else None
        suggestions = []
        if stop_distance <= near_level_pct:
            suggestions.append("Price is near stop-loss; review exposure and feed freshness.")
        if target > 0 and target_distance is not None and target_distance <= near_level_pct:
            is_approaching = (side == "long" and price < target) or (side == "short" and price > target)
            if is_approaching:
                suggestions.append("Price is near TP1; verify the configured partial-exit plan.")
        if trade.get("tp1_hit") and trade.get("move_stop_to_breakeven_after_tp1"):
            stop_at_or_beyond_entry = stop >= entry if side == "long" else stop <= entry
            if not stop_at_or_beyond_entry:
                suggestions.append("TP1 is marked hit but stop is not at break-even; inspect the event journal.")
        if not suggestions:
            suggestions.append("No immediate level-based action suggested; continue monitoring.")
        items.append({
            "trade_id": tid, "symbol": trade.get("symbol"), "side": side,
            "status": status, "market_price": round(price, 10),
            "r_multiple": round(r_multiple, 4) if r_multiple is not None else None,
            "stop_distance_pct": round(stop_distance, 5),
            "tp1_distance_pct": round(target_distance, 5) if target_distance is not None else None,
            "suggestions": suggestions,
        })
    return {
        "status": "completed", "position_count": len(items), "items": items,
        "mode": "read_only_guidance", "execution_allowed": False,
        "limitations": ["Suggestions do not modify stops, positions, or orders.",
                        "Prices must come from the caller or persisted paper-trade state."],
    }
