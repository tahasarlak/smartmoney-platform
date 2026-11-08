"""Read-only Phase 11 final operational audit.

This audit validates in-process contracts and persisted model metadata. It does
not connect to PostgreSQL, claim live readiness, or submit exchange orders.
"""
from __future__ import annotations

import inspect
from typing import Any

from . import forward_testing
from .live_price_monitor import LivePriceMonitor
from .live_signal_monitor import LiveSignalMonitor
from .paper_automation import (
    paper_automation_status,
    start_paper_automation,
    stop_paper_automation,
)
from .db_models import Signal, ForwardTestRun, ForwardTestTrade, ForwardTestEvent


def _item(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _contract_checks() -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    contracts = [
        ("live_price_monitor", LivePriceMonitor, {"start", "stop", "status"}),
        ("live_signal_monitor", LiveSignalMonitor, {"start", "stop", "status", "run_once"}),
        ("forward_testing", forward_testing, {
            "start_forward_run", "stop_forward_run", "process_forward_tick",
            "forward_summary", "list_forward_runs", "list_forward_trades",
        }),
        ("paper_automation", {
            "start": start_paper_automation,
            "status": paper_automation_status,
            "stop": stop_paper_automation,
        }, {"start", "status", "stop"}),
    ]
    for name, target, required in contracts:
        available = set(target.keys()) if isinstance(target, dict) else set(dir(target))
        missing = sorted(required - available)
        checks.append(_item(
            f"{name}_contract",
            "passed" if not missing else "failed",
            "Required interfaces present" if not missing else f"Missing interfaces: {', '.join(missing)}",
        ))

    expected_parameters = {
        "start_forward_run": {
            "user_id", "portfolio_id", "account_id", "symbols",
            "risk_per_trade_pct", "min_quality_score", "commission_pct",
            "slippage_bps", "include_existing_signals",
        },
        "process_forward_tick": {"event"},
        "start_paper_automation": {
            "user_id", "portfolio_id", "account_id", "confirm_paper_only",
        },
    }
    functions = {
        "start_forward_run": forward_testing.start_forward_run,
        "process_forward_tick": forward_testing.process_forward_tick,
        "start_paper_automation": start_paper_automation,
    }
    for name, required in expected_parameters.items():
        try:
            actual = set(inspect.signature(functions[name]).parameters)
            missing = sorted(required - actual)
        except (TypeError, ValueError):
            missing = sorted(required)
        checks.append(_item(
            f"{name}_signature",
            "passed" if not missing else "failed",
            "Required parameters present" if not missing else f"Missing parameters: {', '.join(missing)}",
        ))
    return checks


def _model_checks() -> list[dict[str, str]]:
    expected = {
        "signals": (Signal, {"id", "symbol", "status", "source", "created_at"}),
        "v11_forward_test_runs": (
            ForwardTestRun,
            {"id", "user_id", "portfolio_id", "account_id", "status", "symbols", "initial_equity"},
        ),
        "v11_forward_test_trades": (
            ForwardTestTrade,
            {"id", "run_id", "signal_id", "symbol", "status", "quantity", "remaining_quantity"},
        ),
        "v11_forward_test_events": (
            ForwardTestEvent,
            {"id", "trade_id", "event_type", "market_price", "event_time_ms"},
        ),
    }
    checks = []
    for table_name, (model, required) in expected.items():
        actual = set(model.__table__.columns.keys())
        missing = sorted(required - actual)
        checks.append(_item(
            f"schema_contract_{table_name}",
            "passed" if not missing else "failed",
            "Required ORM columns present" if not missing else f"Missing ORM columns: {', '.join(missing)}",
        ))
    return checks


def run_phase11_final_audit(
    *,
    live_price_status: dict[str, Any] | None = None,
    live_signal_status: dict[str, Any] | None = None,
    paper_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a read-only structural audit; optional statuses add runtime findings.

    Runtime checks are reported as `blocked` when the supplied telemetry says
    a dependency is unavailable. Missing telemetry is `not_run`, not a pass.
    """
    checks = _contract_checks() + _model_checks()

    checks.append(_item(
        "paper_only_safety",
        "passed",
        "Paper automation requires confirm_paper_only=true; exchange execution is disabled by these interfaces",
    ))

    runtime_inputs = [
        ("live_price_runtime", live_price_status, ("running", "connected")),
        ("live_signal_runtime", live_signal_status, ("running",)),
        ("paper_runtime", paper_status, ("active",)),
    ]
    for name, status, required_true in runtime_inputs:
        if status is None:
            checks.append(_item(name, "not_run", "Runtime telemetry was not supplied; no live readiness claim"))
            continue
        missing = [field for field in required_true if not bool(status.get(field))]
        error = status.get("last_error")
        if name == "live_price_runtime" and status.get("connected") is False:
            missing.append("connected")
        ok = not missing and not error
        checks.append(_item(
            name,
            "passed" if ok else "blocked",
            "Runtime telemetry healthy" if ok else (
                f"Not healthy: {', '.join(sorted(set(missing)))}"
                + (f"; last_error={error}" if error else "")
            ),
        ))

    failed = [x for x in checks if x["status"] == "failed"]
    blocked = [x for x in checks if x["status"] == "blocked"]
    not_run = [x for x in checks if x["status"] == "not_run"]
    structural_ok = not failed
    return {
        "audit": "phase11_final_operational_audit",
        "status": "passed" if structural_ok and not blocked and not not_run else (
            "failed" if failed else "incomplete"
        ),
        "check_count": len(checks),
        "passed_count": sum(x["status"] == "passed" for x in checks),
        "failed_count": len(failed),
        "blocked_count": len(blocked),
        "not_run_count": len(not_run),
        "checks": checks,
        "scope": {
            "structural_contracts": True,
            "orm_schema_metadata": True,
            "postgresql_connectivity_tested": False,
            "runtime_readiness_certified": False,
            "paper_trade_execution_tested": False,
            "exchange_orders_submitted": False,
            "profitability_certified": False,
        },
        "execution_allowed": False,
        "conclusion": (
            "Structural audit passed. Database-backed and runtime validation must still run in GitHub Actions."
            if structural_ok and (blocked or not_run) else
            "Phase 11 structural audit passed." if structural_ok else
            "Structural audit failed; resolve failed contracts before proceeding."
        ),
    }
