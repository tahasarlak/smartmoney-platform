import pytest
from app.phase32_strategy_intelligence import evaluate_strategy_candidates
from app.phase33_capital_optimizer import optimize_capital
from app.phase34_execution_safety import execution_preflight
from app.phase35_operations import build_operations_report
from app.phase36_market_data_quality import assess_candle_quality
from app.phase37_quant_validation import validate_return_series
from app.phase38_security_posture import build_security_posture
from app.phase39_release_gate import build_final_release_gate

def candidate(**kw):
    d={"name":"Trend","trade_count":100,"win_rate_pct":55,"profit_factor":1.5,"max_drawdown_pct":5,"expectancy_r":.3,"suitable_regimes":["trending"]}
    d.update(kw); return d

def test_32_strategy_rank():
    r=evaluate_strategy_candidates(market_regime="trending",strategies=[candidate()])
    assert r["eligible_candidate_count"]==1 and r["execution_allowed"] is False

def test_32_transition_not_eligible():
    assert evaluate_strategy_candidates(market_regime="transition",strategies=[candidate()])["eligible_candidate_count"]==0

def test_33_capital_budget():
    r=optimize_capital(equity=500,max_portfolio_risk_pct=3,current_open_risk=2,max_trade_risk_pct=.5,
        proposals=[{"symbol":"BTCUSDT","entry_price":100,"stop_loss":98,"quality_score":100}],max_positions=3)
    assert r["proposals"][0]["risk_cash"]==2.5
    assert r["allocation_committed"] is False

def test_33_budget_exhausted():
    r=optimize_capital(equity=500,max_portfolio_risk_pct=1,current_open_risk=5,max_trade_risk_pct=.5,
        proposals=[{"symbol":"ETHUSDT","entry_price":100,"stop_loss":99}],max_positions=2)
    assert r["proposals"][0]["suggested_quantity"]==0

def test_34_preflight_passes_but_never_submits():
    r=execution_preflight(symbol="BTCUSDT",side="long",quantity=.1,entry_price=100,stop_loss=98,take_profit=105,
        equity=1000,current_open_risk=0,max_portfolio_risk_pct=2,max_trade_risk_pct=1,
        max_open_trades=3,current_open_trades=0)
    assert r["status"]=="preflight_passed" and r["order_submitted"] is False

def test_34_blocks_risk_overrun():
    r=execution_preflight(symbol="BTCUSDT",side="long",quantity=10,entry_price=100,stop_loss=90,take_profit=120,
        equity=1000,current_open_risk=0,max_portfolio_risk_pct=2,max_trade_risk_pct=1,
        max_open_trades=3,current_open_trades=0)
    assert "trade_risk_limit_exceeded" in r["issues"]

def test_35_ops_degraded_without_scheduler():
    r=build_operations_report(database_ok=True,market_data_ok=True,scheduler_configured=False,
        scheduler_running=False,last_cycle_age_seconds=None)
    assert r["status"]=="degraded"

def test_36_good_candles():
    c=[{"time":i*60,"open":10,"high":12,"low":9,"close":11,"volume":2} for i in range(1,5)]
    r=assess_candle_quality(candles=c,timeframe="1m",now_seconds=300,stale_after_seconds=500)
    assert r["status"]=="passed"

def test_36_detects_gap():
    c=[{"time":60,"open":10,"high":12,"low":9,"close":11},{"time":600,"open":10,"high":12,"low":9,"close":11}]
    r=assess_candle_quality(candles=c,timeframe="1m",now_seconds=610)
    assert r["status"]=="degraded"

def test_37_quant_metrics():
    r=validate_return_series(returns_pct=[1,-.5,.8,-.2]*10,minimum_observations=30)
    assert r["status"]=="evaluated" and r["observations"]==40

def test_37_small_sample():
    assert validate_return_series(returns_pct=[1,-1],minimum_observations=30)["status"]=="insufficient_sample"

def test_38_security_missing_controls():
    r=build_security_posture(authenticated=True,database_ok=True,tls_termination_expected=True,
        secret_store_configured=False,api_key_withdrawals_disabled=True,user_isolation_verified=False)
    assert r["status"]=="review_required"

def test_39_live_gate_never_authorizes():
    r=build_final_release_gate(database_ok=True,lifecycle_status="passed",burn_in_status="passed",
        market_data_status="passed",quantitative_status="evaluated",security_status="passed",operations_status="healthy",
        live_broker_adapter_verified=True,durable_scheduler_verified=True,kill_switch_verified=True,multi_user_isolation_verified=True)
    assert r["live_trading_enabled"] is False
    assert r["release_decision"]=="NOT_AUTHORIZED_FOR_LIVE_TRADING"
