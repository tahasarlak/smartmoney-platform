from app.robustness_research import build_robustness_report

def trades(n=40):
 return [{"id":str(i),"status":"closed","net_realized_pnl":10 if i%2 else -5,"planned_entry":100,"initial_stop_loss":90,"quantity":1,"closed_at_ms":1700000000000+i*60000} for i in range(n)]

def test_robustness_metrics_and_guard():
 r=build_robustness_report(trades=trades())
 assert r["status"]=="completed" and r["execution_allowed"] is False
 assert r["stressed_metrics"]["mean_r"] < r["base_metrics"]["mean_r"]

def test_empty_sample():
 assert build_robustness_report(trades=[])["status"]=="insufficient_sample"
