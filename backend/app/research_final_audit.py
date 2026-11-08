"""Read-only research and data-quality audit for TRADF V11 paper portfolios."""
from __future__ import annotations
from typing import Any
from .walk_forward_validation import _trade_r, _timestamp


def build_research_audit(*, trades: list[dict[str, Any]], portfolio: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(trades,list): raise ValueError("trades must be a list")
    valid=[]; missing_time=0; missing_risk=0; duplicate_ids=0; ids=set()
    for t in trades:
        tid=str(t.get("id",""))
        if tid and tid in ids: duplicate_ids+=1
        if tid: ids.add(tid)
        if _timestamp(t) is None: missing_time+=1
        r=_trade_r(t)
        if r is None: missing_risk+=1
        else: valid.append(r)
    n=len(valid)
    checks=[
      {"name":"portfolio_scope","status":"passed" if bool(portfolio) else "failed"},
      {"name":"closed_trade_sample","status":"passed" if n>=30 else "insufficient_sample","value":n,"minimum":30},
      {"name":"trade_timestamps","status":"passed" if missing_time==0 else "warning","missing":missing_time},
      {"name":"risk_normalization","status":"passed" if missing_risk==0 else "warning","invalid_or_missing":missing_risk},
      {"name":"duplicate_trade_ids","status":"passed" if duplicate_ids==0 else "warning","duplicates":duplicate_ids},
      {"name":"live_execution_guard","status":"passed","execution_allowed":False},
    ]
    failed=sum(c["status"]=="failed" for c in checks)
    warnings=sum(c["status"] in ("warning","insufficient_sample") for c in checks)
    return {"status":"passed_with_warnings" if warnings and not failed else "passed" if not failed else "failed",
            "audit":"tradf_v11_research_data_quality_audit","check_count":len(checks),
            "passed_count":sum(c["status"]=="passed" for c in checks),"warning_count":warnings,
            "failed_count":failed,"valid_closed_trade_count":n,"checks":checks,
            "scope":{"database_schema_changes":False,"exchange_connectivity_test":False,
                     "profitability_certification":False,"live_readiness_certification":False},
            "execution_allowed":False,
            "conclusion":"Read-only paper-data audit only; passing checks do not certify strategy profitability or live-trading readiness."}
