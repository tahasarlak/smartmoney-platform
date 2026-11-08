"""Phase 39: conservative final release gate. Live readiness is blocked by design."""
from __future__ import annotations
from typing import Any

def build_final_release_gate(*, database_ok: bool, lifecycle_status: str,
                             burn_in_status: str, market_data_status: str,
                             quantitative_status: str, security_status: str,
                             operations_status: str, live_broker_adapter_verified: bool,
                             durable_scheduler_verified: bool, kill_switch_verified: bool,
                             multi_user_isolation_verified: bool) -> dict[str, Any]:
    gates=[
        ("database",database_ok),
        ("paper_lifecycle",lifecycle_status=="passed"),
        ("paper_burn_in",burn_in_status=="passed"),
        ("market_data_quality",market_data_status=="passed"),
        ("quantitative_validation",quantitative_status=="evaluated"),
        ("security_posture",security_status=="passed"),
        ("operations",operations_status=="healthy"),
        ("live_broker_adapter",live_broker_adapter_verified),
        ("durable_scheduler",durable_scheduler_verified),
        ("emergency_kill_switch",kill_switch_verified),
        ("multi_user_isolation",multi_user_isolation_verified),
    ]
    rows=[{"gate":name,"passed":bool(ok)} for name,ok in gates]
    blockers=[x["gate"] for x in rows if not x["passed"]]
    # Explicit policy: a live release is not authorized by this report.
    return {"status":"paper_release_candidate" if not blockers else "not_release_ready",
            "gates":rows,"blockers":blockers,"paper_mode_only":True,
            "live_trading_enabled":False,"execution_allowed":False,
            "release_decision":"NOT_AUTHORIZED_FOR_LIVE_TRADING",
            "limitations":["This is a readiness checklist, not a certification or profitability assessment.",
                           "A live broker adapter, exchange testnet verification, durable scheduler, kill switch and independent security review are required.",
                           "Run a sustained paper-trading observation period and verify backup restoration before any real-capital pilot."]}
