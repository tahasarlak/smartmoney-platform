"""Phase 31: read-only paper-trading burn-in and journal reconciliation.

This module analyzes persisted paper execution trades and their immutable events.
It does not create, modify, or execute orders and does not run a background scheduler.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

_ALLOWED_STATUSES = {"pending_entry", "open", "partially_closed", "closed", "cancelled"}
_EXIT_EVENTS = {
    "STOP_FILLED", "MANUAL_CLOSE_FILLED", "TP1_FILLED", "TP2_FILLED", "TP3_FILLED",
}


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _timestamp_ms(value: Any) -> int:
    try:
        result = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return result if result >= 0 else 0


def build_burn_in_report(
    *,
    trades: list[dict[str, Any]],
    events_by_trade: dict[str, list[dict[str, Any]]],
    now_ms: int,
    window_hours: int = 24,
    stale_after_seconds: int = 300,
    minimum_events: int = 5,
    minimum_observation_minutes: int = 30,
) -> dict[str, Any]:
    """Build a conservative operational report from persisted paper journal rows.

    A passed status means the supplied sample met these report checks only. It is
    not proof of continuous uptime, feed completeness, profitability, or live readiness.
    """
    if isinstance(now_ms, bool) or int(now_ms) <= 0:
        raise ValueError("now_ms must be a positive integer")
    if not 1 <= int(window_hours) <= 720:
        raise ValueError("window_hours must be between 1 and 720")
    if not 10 <= int(stale_after_seconds) <= 86400:
        raise ValueError("stale_after_seconds must be between 10 and 86400")
    if not 1 <= int(minimum_events) <= 10000:
        raise ValueError("minimum_events must be between 1 and 10000")
    if not 1 <= int(minimum_observation_minutes) <= int(window_hours) * 60:
        raise ValueError("minimum_observation_minutes must fit within the selected window")

    now = int(now_ms)
    cutoff = now - int(window_hours) * 3_600_000
    stale_ms = int(stale_after_seconds) * 1000
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    total_events = 0
    window_events = 0
    active_count = 0
    closed_count = 0
    pending_count = 0
    net_realized = 0.0
    observed_times: list[int] = []
    stale_active: list[str] = []
    per_trade: list[dict[str, Any]] = []

    def add_issue(trade_id: str, code: str, detail: str) -> None:
        issues.append({"trade_id": trade_id, "code": code, "detail": detail})

    for trade in trades:
        trade_id = str(trade.get("id") or "")
        status = str(trade.get("status") or "")
        quantity = _finite(trade.get("quantity"), float("nan"))
        remaining = _finite(trade.get("remaining_quantity"), float("nan"))
        realized = _finite(trade.get("realized_pnl"), float("nan"))
        fees = _finite(trade.get("fees_paid"), float("nan"))

        if not trade_id:
            add_issue("", "missing_trade_id", "Persisted trade has no identifier.")
            continue
        if status not in _ALLOWED_STATUSES:
            add_issue(trade_id, "invalid_trade_status", f"Unsupported status: {status}")
        if not all(math.isfinite(x) for x in (quantity, remaining, realized, fees)):
            add_issue(trade_id, "non_finite_trade_values", "Trade quantity, remaining quantity, P&L and fees must be finite.")
            continue
        if quantity <= 0 or remaining < -1e-9 or remaining > quantity + 1e-9:
            add_issue(trade_id, "invalid_quantity_bounds", "Remaining quantity must be between zero and original quantity.")
        if fees < -1e-9:
            add_issue(trade_id, "negative_fees", "Accumulated fees cannot be negative.")
        if status == "closed" and remaining > 1e-8:
            add_issue(trade_id, "closed_trade_has_remaining_quantity", "Closed trade has a non-zero remaining quantity.")
        if status in {"open", "partially_closed"} and remaining > 0 and not _finite(trade.get("avg_entry_price")) > 0:
            add_issue(trade_id, "active_trade_missing_entry_price", "Active filled trade has no valid average entry price.")

        if status in {"pending_entry", "open", "partially_closed"} and remaining > 0:
            active_count += 1
        if status == "pending_entry":
            pending_count += 1
        if status == "closed":
            closed_count += 1

        events = list(events_by_trade.get(trade_id, []))
        total_events += len(events)
        if not events:
            add_issue(trade_id, "missing_event_journal", "Trade has no persisted execution journal events.")

        ordered = sorted(events, key=lambda item: (
            _timestamp_ms(item.get("event_time_ms")),
            int(item.get("sequence_no", 0) or 0),
            int(item.get("id", 0) or 0),
        ))
        if events != ordered:
            add_issue(trade_id, "events_not_chronological", "Journal events are not stored in chronological order.")

        seen: set[tuple[str, int]] = set()
        event_pnl = 0.0
        event_fees = 0.0
        exited_quantity = 0.0
        trade_window_events = 0
        last_event_ms = 0

        for event in events:
            event_ms = _timestamp_ms(event.get("event_time_ms"))
            last_event_ms = max(last_event_ms, event_ms)
            if event_ms >= cutoff:
                trade_window_events += 1
                window_events += 1
                observed_times.append(event_ms)
            if event_ms > now + 300_000:
                add_issue(trade_id, "future_dated_event", "Journal event timestamp is more than five minutes in the future.")
            source = str(event.get("source_event_id") or "")
            try:
                sequence = int(event.get("sequence_no", 0) or 0)
            except (TypeError, ValueError):
                sequence = -1
            key = (source, sequence)
            if not source or sequence < 0 or key in seen:
                add_issue(trade_id, "invalid_or_duplicate_event_key", "Event source ID and sequence number must be valid and unique per trade.")
            seen.add(key)

            event_pnl_value = _finite(event.get("pnl"), float("nan"))
            fee_value = _finite(event.get("fee"), float("nan"))
            event_qty = _finite(event.get("quantity"), float("nan"))
            if not all(math.isfinite(x) for x in (event_pnl_value, fee_value, event_qty)):
                add_issue(trade_id, "non_finite_event_values", "Event P&L, fee and quantity must be finite.")
                continue
            if fee_value < -1e-9 or event_qty < -1e-9:
                add_issue(trade_id, "negative_event_fee_or_quantity", "Event fee and quantity cannot be negative.")
            event_pnl += event_pnl_value
            event_fees += fee_value
            if event.get("event_type") in _EXIT_EVENTS:
                exited_quantity += event_qty

        if events:
            if not math.isclose(event_pnl, realized, rel_tol=1e-7, abs_tol=1e-6):
                add_issue(trade_id, "realized_pnl_journal_mismatch", "Trade realized P&L does not match the event journal.")
            if not math.isclose(event_fees, fees, rel_tol=1e-7, abs_tol=1e-6):
                add_issue(trade_id, "fees_journal_mismatch", "Trade accumulated fees do not match the event journal.")
            if status in {"closed", "partially_closed"}:
                actual_exited = max(0.0, quantity - remaining)
                if not math.isclose(exited_quantity, actual_exited, rel_tol=1e-7, abs_tol=1e-6):
                    add_issue(trade_id, "exit_quantity_journal_mismatch", "Exited quantity does not match the event journal.")

        if status in {"pending_entry", "open", "partially_closed"} and remaining > 0:
            if last_event_ms <= 0 or now - last_event_ms > stale_ms:
                stale_active.append(trade_id)

        net_realized += realized - fees
        per_trade.append({
            "trade_id": trade_id,
            "symbol": str(trade.get("symbol") or ""),
            "status": status,
            "event_count": len(events),
            "window_event_count": trade_window_events,
            "last_event_time_ms": last_event_ms or None,
            "net_realized_pnl": round(realized - fees, 8),
        })

    if stale_active:
        warnings.append({
            "code": "stale_active_trade_updates",
            "detail": f"{len(stale_active)} active paper trade(s) have no recent journal update.",
        })

    observation_span_ms = max(observed_times) - min(observed_times) if len(observed_times) >= 2 else 0
    observation_minutes = round(observation_span_ms / 60_000, 2)
    observation_requirement_met = observation_minutes >= minimum_observation_minutes
    activity_requirement_met = window_events >= minimum_events
    integrity_ok = not issues

    if not trades or window_events == 0:
        status = "insufficient_activity"
    elif not integrity_ok:
        status = "review_required"
    elif stale_active:
        status = "degraded"
    elif not activity_requirement_met or not observation_requirement_met:
        status = "insufficient_observation"
    else:
        status = "passed"

    return {
        "status": status,
        "portfolio_trade_count": len(trades),
        "active_trade_count": active_count,
        "pending_entry_count": pending_count,
        "closed_trade_count": closed_count,
        "journal_event_count": total_events,
        "window_event_count": window_events,
        "window_hours": int(window_hours),
        "observation_span_minutes": observation_minutes,
        "minimum_observation_minutes": int(minimum_observation_minutes),
        "minimum_events": int(minimum_events),
        "activity_requirement_met": activity_requirement_met,
        "observation_requirement_met": observation_requirement_met,
        "stale_active_trade_ids": stale_active[:100],
        "integrity_issue_count": len(issues),
        "issues": issues[:250],
        "warnings": warnings,
        "realized_net_pnl": round(net_realized, 8),
        "trades": per_trade[:500],
        "mode": "read_only_paper_burn_in",
        "execution_allowed": False,
        "scope": "persisted tenant-scoped V11 paper execution trades and immutable execution event journal",
        "limitations": [
            "This endpoint is an on-demand report; it does not run a continuous background burn-in scheduler.",
            "A passed result validates only the returned database sample and selected observation thresholds.",
            "It does not prove market-feed completeness, continuous uptime, backup recoverability, profitability, or live-execution readiness.",
            "Only V11 ExecutionTrade records are included; legacy PaperOrder and forward-test records are excluded.",
        ],
    }
