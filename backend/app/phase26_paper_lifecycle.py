"""Phase 26: reconciliation checks for persisted paper execution lifecycles."""
from __future__ import annotations
import math
from typing import Any

_EXIT_EVENTS = {
    "STOP_FILLED", "MANUAL_CLOSE_FILLED", "TP1_FILLED", "TP2_FILLED", "TP3_FILLED",
}

def build_lifecycle_validation(*, trades: list[dict[str, Any]],
                               events_by_trade: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    checked_events = 0
    net_realized = 0.0
    closed = active = 0

    def issue(trade_id: str, code: str, detail: str):
        issues.append({"trade_id": trade_id, "code": code, "detail": detail})

    for trade in trades:
        tid = str(trade.get("id") or "")
        status = str(trade.get("status") or "")
        try:
            quantity = float(trade.get("quantity", 0))
            remaining = float(trade.get("remaining_quantity", 0))
            realized = float(trade.get("realized_pnl", 0))
            fees = float(trade.get("fees_paid", 0))
            if not all(math.isfinite(x) for x in (quantity, remaining, realized, fees)):
                raise ValueError
        except (TypeError, ValueError):
            issue(tid, "non_finite_trade_fields", "Quantity, remaining quantity, P&L and fees must be finite.")
            continue
        if not tid:
            issue(tid, "missing_trade_id", "Trade has no identifier.")
        if quantity <= 0 or remaining < -1e-9 or remaining > quantity + 1e-9:
            issue(tid, "invalid_quantity_bounds", "Remaining quantity must be between zero and original quantity.")
        if status not in {"pending_entry", "open", "partially_closed", "closed", "cancelled"}:
            issue(tid, "invalid_status", f"Unsupported status: {status}")
        if status == "closed" and remaining > max(1e-9, quantity * 1e-8):
            issue(tid, "closed_with_remaining_quantity", "Closed trade still has remaining quantity.")
        if status == "pending_entry" and trade.get("avg_entry_price") is not None:
            issue(tid, "pending_entry_has_fill", "Pending entry unexpectedly has an average fill price.")
        if status in {"open", "partially_closed"} and not trade.get("avg_entry_price"):
            issue(tid, "active_trade_missing_entry_fill", "Active trade has no average entry fill.")
        if status in {"open", "partially_closed", "pending_entry"}:
            active += 1
        if status == "closed":
            closed += 1

        events = list(events_by_trade.get(tid, []))
        checked_events += len(events)
        ordered = sorted(events, key=lambda e: (int(e.get("event_time_ms", 0)), int(e.get("sequence_no", 0))))
        if events != ordered:
            issue(tid, "events_not_chronological", "Execution events are not in chronological order.")
        seen: set[tuple[str, int]] = set()
        event_gross = event_fees = exited_qty = 0.0
        for event in events:
            source = str(event.get("source_event_id") or "")
            sequence = int(event.get("sequence_no", 0))
            key = (source, sequence)
            if not source or key in seen:
                issue(tid, "duplicate_or_missing_event_key", "Event source/sequence key is missing or duplicated.")
            seen.add(key)
            try:
                pnl = float(event.get("pnl", 0))
                fee = float(event.get("fee", 0))
                qty = float(event.get("quantity", 0))
                if not all(math.isfinite(x) for x in (pnl, fee, qty)) or fee < 0 or qty < 0:
                    raise ValueError
            except (TypeError, ValueError):
                issue(tid, "invalid_event_numeric", "Event P&L, fee and quantity must be finite and non-negative where applicable.")
                continue
            event_gross += pnl
            event_fees += fee
            if event.get("event_type") in _EXIT_EVENTS:
                exited_qty += qty
        if events:
            if not math.isclose(event_gross, realized, rel_tol=1e-7, abs_tol=1e-6):
                issue(tid, "realized_pnl_mismatch", "Trade realized P&L does not reconcile to journal event P&L.")
            if not math.isclose(event_fees, fees, rel_tol=1e-7, abs_tol=1e-6):
                issue(tid, "fees_mismatch", "Trade fees do not reconcile to journal event fees.")
            if status in {"closed", "partially_closed", "stopped"} and quantity > 0:
                if not math.isclose(max(0.0, quantity - remaining), exited_qty, rel_tol=1e-7, abs_tol=1e-6):
                    issue(tid, "exit_quantity_mismatch", "Exited event quantity does not reconcile to remaining quantity.")
        net_realized += realized - fees

    status = "passed" if not issues else "review_required"
    return {
        "status": status,
        "trade_count": len(trades),
        "active_trade_count": active,
        "closed_trade_count": closed,
        "event_count_checked": checked_events,
        "realized_net_pnl": round(net_realized, 8),
        "integrity_issue_count": len(issues),
        "issues": issues[:250],
        "execution_allowed": False,
        "method": "persisted_execution_trade_and_immutable_event_journal_reconciliation",
        "limitations": [
            "Checks only the supplied persisted paper-trade sample.",
            "Does not prove market-feed completeness, backup recoverability, or exchange execution readiness.",
        ],
    }
