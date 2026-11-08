"""Phase 25: scoped reliability and consistency report."""
from __future__ import annotations
from typing import Any

def build_reliability_report(*, database_probe_ok: bool, trades: list[dict[str, Any]],
                             paper_control: dict[str, Any], alerts: dict[str, Any]) -> dict[str, Any]:
    checks = [
        {"name": "postgresql_read_probe", "status": "passed" if database_probe_ok else "failed"},
        {"name": "paper_execution_only", "status": "passed"},
        {"name": "trade_lifecycle_integrity",
         "status": "passed" if paper_control.get("integrity_issue_count", 0) == 0 else "warning",
         "issue_count": int(paper_control.get("integrity_issue_count", 0))},
        {"name": "active_trade_price_freshness",
         "status": "warning" if any(a.get("code") in {"stale_market_update", "price_unavailable"} for a in alerts.get("alerts", [])) else "passed"},
    ]
    status = "ok" if all(c["status"] == "passed" for c in checks) else ("degraded" if any(c["status"] == "failed" for c in checks) else "review_required")
    return {
        "status": status, "checks": checks, "trade_count": len(trades),
        "active_trade_count": int(paper_control.get("active_trade_count", 0)),
        "execution_allowed": False,
        "scope": "authenticated tenant portfolio, persisted paper trades and one database read probe",
        "limitations": [
            "Does not test multi-instance locks, scheduler liveness, external alert delivery, backups, restore procedures, or load capacity.",
            "A passing report is not a production reliability certification."
        ]
    }
