"""Phase 24: alerts derived only from persisted paper trade state."""
from __future__ import annotations
from typing import Any

def build_trade_alerts(*, trades: list[dict[str, Any]], now_ms: int,
                       stale_after_seconds: int = 180, near_level_pct: float = 0.5) -> dict[str, Any]:
    if now_ms <= 0 or stale_after_seconds < 1 or not 0 < near_level_pct <= 10:
        raise ValueError("Invalid alert timing or proximity settings")
    alerts: list[dict[str, Any]] = []
    for trade in trades:
        if trade.get("status") not in {"pending_entry", "open", "partially_closed"}:
            continue
        trade_id = str(trade.get("id", ""))
        symbol = str(trade.get("symbol", "UNKNOWN"))
        price = trade.get("last_price")
        event_ms = int(trade.get("last_event_time_ms", 0) or 0)
        if price is None or float(price) <= 0:
            alerts.append({"severity": "warning", "code": "price_unavailable",
                           "trade_id": trade_id, "symbol": symbol,
                           "message": "No persisted market price is available for this active paper trade."})
            continue
        price = float(price)
        if event_ms <= 0 or now_ms - event_ms > stale_after_seconds * 1000:
            age = None if event_ms <= 0 else max(0, (now_ms - event_ms) // 1000)
            alerts.append({"severity": "warning", "code": "stale_market_update",
                           "trade_id": trade_id, "symbol": symbol, "age_seconds": age,
                           "message": "The latest persisted market update is missing or stale."})
        side = str(trade.get("side", "")).lower()
        stop = float(trade.get("stop_loss", 0) or 0)
        target = float(trade.get("tp1", 0) or 0)
        if stop > 0:
            stop_distance = abs(price - stop) / price * 100
            if stop_distance <= near_level_pct:
                alerts.append({"severity": "critical", "code": "near_stop_loss",
                               "trade_id": trade_id, "symbol": symbol,
                               "distance_pct": round(stop_distance, 5),
                               "message": "Price is near the configured stop-loss level."})
        if target > 0:
            target_distance = abs(target - price) / price * 100
            target_relevant = (side == "long" and price < target) or (side == "short" and price > target)
            if target_relevant and target_distance <= near_level_pct:
                alerts.append({"severity": "info", "code": "near_first_target",
                               "trade_id": trade_id, "symbol": symbol,
                               "distance_pct": round(target_distance, 5),
                               "message": "Price is near the first take-profit level."})
    alerts.sort(key=lambda x: {"critical": 0, "warning": 1, "info": 2}.get(x["severity"], 3))
    return {"status": "alerts_present" if alerts else "clear", "alert_count": len(alerts),
            "alerts": alerts[:200], "source": "persisted_paper_execution_state",
            "execution_allowed": False,
            "limitations": ["Alerts are computed on request from persisted trade state; no background push or guaranteed real-time delivery is configured."]}
