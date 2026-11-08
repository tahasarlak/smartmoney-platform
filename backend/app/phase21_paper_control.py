"""Phase 21: tenant-scoped paper execution lifecycle reconciliation."""
from __future__ import annotations
from collections import Counter
from typing import Any

ACTIVE = {"pending_entry", "open", "partially_closed"}
TERMINAL = {"closed", "cancelled"}
VALID = ACTIVE | TERMINAL

def build_paper_control_report(*, trades: list[dict[str, Any]],
                               events_by_trade: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if not isinstance(trades, list) or not isinstance(events_by_trade, dict):
        raise ValueError("trades and events_by_trade have invalid types")
    statuses = Counter()
    event_types = Counter()
    issues: list[dict[str, str]] = []
    net_realized = 0.0
    fees = 0.0
    active_count = 0
    closed_count = 0
    event_count = 0
    for trade in trades:
        trade_id = str(trade.get("id", ""))
        status = str(trade.get("status", ""))
        if not trade_id:
            issues.append({"trade_id": "unknown", "issue": "missing_trade_id"})
        if status not in VALID:
            issues.append({"trade_id": trade_id or "unknown", "issue": "invalid_status"})
        statuses[status] += 1
        qty = float(trade.get("quantity", 0) or 0)
        remaining = float(trade.get("remaining_quantity", 0) or 0)
        if qty <= 0 or remaining < -1e-9 or remaining > qty + 1e-9:
            issues.append({"trade_id": trade_id, "issue": "invalid_quantity_state"})
        if status in TERMINAL and remaining > 1e-9:
            issues.append({"trade_id": trade_id, "issue": "terminal_trade_has_remaining_quantity"})
        if status in ACTIVE and remaining <= 1e-9:
            issues.append({"trade_id": trade_id, "issue": "active_trade_has_no_remaining_quantity"})
        if status in ACTIVE:
            active_count += 1
        if status == "closed":
            closed_count += 1
        realized = float(trade.get("realized_pnl", 0) or 0)
        fee = float(trade.get("fees_paid", 0) or 0)
        net_realized += realized - fee
        fees += fee
        events = events_by_trade.get(trade_id, [])
        event_count += len(events)
        seen: set[tuple[str, int]] = set()
        last_time = -1
        for event in events:
            event_types[str(event.get("event_type", "unknown"))] += 1
            key = (str(event.get("source_event_id", "")), int(event.get("sequence_no", 0) or 0))
            if key in seen:
                issues.append({"trade_id": trade_id, "issue": "duplicate_event_identity"})
            seen.add(key)
            event_time = int(event.get("event_time_ms", 0) or 0)
            if event_time and last_time > event_time:
                issues.append({"trade_id": trade_id, "issue": "event_time_not_monotonic"})
            if event_time:
                last_time = event_time
    return {
        "status": "passed" if not issues else "review_required",
        "trade_count": len(trades), "active_trade_count": active_count,
        "closed_trade_count": closed_count, "status_counts": dict(statuses),
        "event_count": event_count, "event_type_counts": dict(event_types),
        "realized_net_pnl": round(net_realized, 8), "fees_paid": round(fees, 8),
        "integrity_issue_count": len(issues), "integrity_issues": issues[:100],
        "mode": "paper", "execution_allowed": False,
        "limitations": [
            "Reconciles persisted V11 ExecutionTrade and ExecutionEvent records only.",
            "Does not reconcile legacy PaperOrder or ForwardTestTrade records.",
            "This is a read-only audit; it does not repair or mutate records."
        ],
    }
