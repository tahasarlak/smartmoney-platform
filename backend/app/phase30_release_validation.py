"""Phase 30: scoped release-readiness gate for the paper-trading platform."""
from __future__ import annotations
from typing import Any

def build_release_validation(*, database_probe_ok: bool,
                             lifecycle_report: dict[str, Any],
                             paper_only: bool = True,
                             required_features: dict[str, bool] | None = None) -> dict[str, Any]:
    required = required_features or {}
    checks = [
        {"name": "postgresql_read_probe", "status": "passed" if database_probe_ok else "failed"},
        {"name": "paper_execution_only", "status": "passed" if paper_only else "failed"},
        {"name": "paper_lifecycle_integrity",
         "status": "passed" if lifecycle_report.get("status") == "passed" else "review_required",
         "issue_count": int(lifecycle_report.get("integrity_issue_count", 0))},
    ]
    for name, available in sorted(required.items()):
        checks.append({"name": str(name), "status": "passed" if available else "review_required"})
    failed = any(c["status"] == "failed" for c in checks)
    review = any(c["status"] == "review_required" for c in checks)
    status = "blocked" if failed else "review_required" if review else "paper_release_candidate"
    return {
        "status": status, "checks": checks,
        "passed_count": sum(c["status"] == "passed" for c in checks),
        "failed_count": sum(c["status"] == "failed" for c in checks),
        "review_count": sum(c["status"] == "review_required" for c in checks),
        "live_trading_enabled": False, "execution_allowed": False,
        "scope": "limited paper-trading release gate using database probe and lifecycle reconciliation",
        "limitations": [
            "Not a security certification, load test, backup restore test, or live-trading approval.",
            "A paper_release_candidate status is not authorization to enable exchange orders.",
        ],
    }
