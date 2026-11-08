"""Read-only operational checks for the TRADF API and PostgreSQL connection."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import text


def build_operational_report(*, session_factory: Any, live_execution_enabled: bool = False) -> dict[str, Any]:
    checks=[]
    try:
        factory=session_factory
        with factory() as session:
            session.execute(text("SELECT 1"))
        checks.append({"name":"postgresql_probe","status":"passed"})
    except Exception as exc:
        checks.append({"name":"postgresql_probe","status":"failed","detail":type(exc).__name__})
    checks.append({"name":"live_execution_guard","status":"passed" if not live_execution_enabled else "warning",
                   "execution_enabled":bool(live_execution_enabled)})
    status="ok" if all(c["status"]=="passed" for c in checks) else "degraded"
    return {"status":status,"checked_at":datetime.now(timezone.utc).isoformat(),"checks":checks,
            "execution_allowed":False,"scope":"API process and one PostgreSQL SELECT 1 probe",
            "limitations":["This endpoint does not verify Binance connectivity, scheduler freshness, alert delivery, backups, or multi-instance health."]}
