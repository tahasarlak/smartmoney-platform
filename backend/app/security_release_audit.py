"""Conservative read-only security and release checks; not a penetration test."""
from __future__ import annotations
from typing import Any


def build_security_audit(*, authenticated_user: dict[str, Any], portfolio: dict[str, Any],
                         live_execution_enabled: bool = False) -> dict[str, Any]:
    checks=[
      {"name":"authenticated_request","status":"passed" if bool(authenticated_user.get("id")) else "failed"},
      {"name":"portfolio_context","status":"passed" if bool(portfolio.get("id")) else "failed"},
      {"name":"live_execution_disabled","status":"passed" if not live_execution_enabled else "failed"},
      {"name":"no_secret_values_returned","status":"not_assessed","detail":"This report contains no credentials; deployment secret storage requires separate review."},
      {"name":"rate_limiting_and_dependency_scanning","status":"not_assessed","detail":"Must be verified in deployment configuration and CI."},
    ]
    failures=sum(1 for c in checks if c["status"]=="failed")
    return {"status":"passed" if failures==0 else "failed","checks":checks,
            "execution_allowed":False,
            "limitations":["This is a narrow application-level checklist, not a penetration test or full security certification.",
                            "TLS, CORS, rate limits, dependency vulnerabilities, secret rotation, and backup access must be audited separately."]}


def build_release_audit(*, performance: dict[str, Any], validation: dict[str, Any],
                        walk_forward: dict[str, Any], research_audit: dict[str, Any],
                        security_audit: dict[str, Any], operational_report: dict[str, Any]) -> dict[str, Any]:
    components={"performance":performance.get("status","unknown"),
                "statistical_validation":validation.get("status","unknown"),
                "walk_forward":walk_forward.get("status","unknown"),
                "research_audit":research_audit.get("status","unknown"),
                "security_audit":security_audit.get("status","unknown"),
                "operations":operational_report.get("status","unknown")}
    return {"status":"review_required" if any(v not in ("passed","completed","ok") for v in components.values()) else "research_checks_passed",
            "components":components,"execution_allowed":False,
            "release_scope":"research and paper-trading validation only",
            "limitations":["Passing these checks does not certify profitability or readiness for live trading.",
                            "A separate human review of infrastructure, security, legal, and operational controls is required."]}
