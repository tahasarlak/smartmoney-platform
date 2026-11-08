from app.research_final_audit import build_research_audit

def test_audit_warns_on_small_sample_and_never_enables_execution():
 r=build_research_audit(trades=[],portfolio={"id":"p"})
 assert r["status"]=="passed_with_warnings"
 assert r["execution_allowed"] is False
 assert r["scope"]["live_readiness_certification"] is False

def test_audit_counts_duplicates_and_invalid():
 t={"id":"x","status":"closed","net_realized_pnl":1,"planned_entry":10,"initial_stop_loss":10,"quantity":1}
 r=build_research_audit(trades=[t,t],portfolio={"id":"p"})
 assert r["checks"][-2]["duplicates"]==1
