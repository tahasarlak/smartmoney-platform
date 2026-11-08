from app.monte_carlo_research import run_monte_carlo

def trades(n=40):
    return [{"id":str(i),"status":"closed","net_realized_pnl":(10 if i%2 else -5),"planned_entry":100,"initial_stop_loss":90,"quantity":1,"closed_at_ms":1700000000000+i*60000} for i in range(n)]

def test_insufficient_sample():
    assert run_monte_carlo(trades=trades(5))["status"]=="insufficient_sample"

def test_completed_reproducible():
    a=run_monte_carlo(trades=trades(),simulations=500,horizon=10,seed=3)
    b=run_monte_carlo(trades=trades(),simulations=500,horizon=10,seed=3)
    assert a==b and a["status"]=="completed" and a["execution_allowed"] is False

def test_bounds():
    try: run_monte_carlo(trades=trades(),simulations=10)
    except ValueError: pass
    else: assert False
