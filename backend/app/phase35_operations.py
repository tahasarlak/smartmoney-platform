"""Phase 35: operational checks and recovery posture, on demand only."""
from __future__ import annotations
from typing import Any

def build_operations_report(*, database_ok: bool, market_data_ok: bool,
                            scheduler_configured: bool, scheduler_running: bool,
                            last_cycle_age_seconds: float | None,
                            error_count_24h: int = 0) -> dict[str, Any]:
    checks=[
        {"name":"database","ok":bool(database_ok),"detail":"Database probe succeeded" if database_ok else "Database probe failed"},
        {"name":"market_data","ok":bool(market_data_ok),"detail":"Market data probe succeeded" if market_data_ok else "Market data unavailable or stale"},
        {"name":"scheduler_configured","ok":bool(scheduler_configured),"detail":"Scheduler configured" if scheduler_configured else "No durable scheduler configuration reported"},
        {"name":"scheduler_running","ok":bool(scheduler_running),"detail":"Scheduler reports running" if scheduler_running else "Scheduler is not confirmed running"},
    ]
    if last_cycle_age_seconds is None:
        checks.append({"name":"last_cycle","ok":False,"detail":"No successful cycle timestamp available"})
    else:
        age=float(last_cycle_age_seconds)
        checks.append({"name":"last_cycle","ok":0 <= age <= 600,"detail":f"Last cycle age: {age:.1f}s"})
    checks.append({"name":"error_budget","ok":int(error_count_24h)==0,"detail":f"{int(error_count_24h)} errors reported in 24h"})
    blockers=[c["name"] for c in checks if not c["ok"]]
    return {"status":"healthy" if not blockers else "degraded","checks":checks,"blockers":blockers,
            "error_count_24h":int(error_count_24h),"automatic_recovery_verified":False,
            "execution_allowed":False,
            "limitations":["This is an on-demand snapshot, not continuous monitoring.",
                           "A process-local running flag does not prove durable scheduling or recovery after deploy."]}
