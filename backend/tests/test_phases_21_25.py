import pytest

from app.phase21_paper_control import build_paper_control_report
from app.phase22_execution_controls import build_execution_preflight
from app.phase23_adaptive_risk import recommend_adaptive_risk
from app.phase24_realtime_intelligence import build_trade_alerts
from app.phase25_reliability import build_reliability_report


def test_phase21_reconciles_paper_trade_and_event():
    trade = {"id":"t1","status":"closed","quantity":2,"remaining_quantity":0,
             "realized_pnl":12,"fees_paid":1}
    events = {"t1":[{"source_event_id":"e1","sequence_no":0,"event_type":"TP1",
                     "event_time_ms":1000}]}
    result = build_paper_control_report(trades=[trade], events_by_trade=events)
    assert result["status"] == "passed"
    assert result["realized_net_pnl"] == 11
    assert result["closed_trade_count"] == 1


def test_phase21_flags_invalid_active_quantity():
    trade = {"id":"t1","status":"open","quantity":1,"remaining_quantity":0}
    result = build_paper_control_report(trades=[trade], events_by_trade={})
    assert result["status"] == "review_required"
    assert result["integrity_issue_count"] >= 1


def test_phase22_preflight_passes_within_limits():
    portfolio = {"cash_equity":10000,"open_risk_cash":100,"max_open_trades":4,
                 "max_trade_risk_pct":1,"max_portfolio_risk_pct":3}
    result = build_execution_preflight(portfolio=portfolio, trades=[], side="long",
                                       quantity=1, entry=100, stop_loss=90)
    assert result["status"] == "passed"
    assert result["proposed_risk_cash"] == 10
    assert result["execution_allowed"] is False


def test_phase22_preflight_rejects_excess_risk():
    portfolio = {"cash_equity":1000,"open_risk_cash":25,"max_open_trades":4,
                 "max_trade_risk_pct":1,"max_portfolio_risk_pct":3}
    result = build_execution_preflight(portfolio=portfolio, trades=[], side="long",
                                       quantity=2, entry=100, stop_loss=90)
    assert result["status"] == "rejected"
    assert "single_trade_risk_limit_exceeded" in result["rejection_reasons"]


def test_phase22_rejects_wrong_stop_side():
    with pytest.raises(ValueError):
        build_execution_preflight(portfolio={"cash_equity":1000}, trades=[],
                                  side="long", quantity=1, entry=100, stop_loss=101)


def test_phase23_reduces_risk_in_high_volatility():
    result = recommend_adaptive_risk(baseline_risk_pct=.5, max_risk_pct=1,
                                     volatility_multiple=2, drawdown_pct=3,
                                     market_regime="high_volatility")
    assert result["recommended_risk_pct"] < .5
    assert result["execution_allowed"] is False


def test_phase23_recommends_pause_at_large_drawdown():
    result = recommend_adaptive_risk(drawdown_pct=9)
    assert result["status"] == "pause_recommended"
    assert result["recommended_risk_pct"] == 0


def test_phase24_detects_near_stop_and_stale_price():
    trade = {"id":"t1","symbol":"BTCUSDT","status":"open","last_price":100,
             "last_event_time_ms":1000,"side":"long","stop_loss":99.8,"tp1":110}
    result = build_trade_alerts(trades=[trade], now_ms=500000, stale_after_seconds=180,
                                near_level_pct=.5)
    codes = {x["code"] for x in result["alerts"]}
    assert "near_stop_loss" in codes
    assert "stale_market_update" in codes


def test_phase24_no_alert_for_terminal_trade():
    trade = {"id":"t1","symbol":"BTCUSDT","status":"closed","last_price":100,
             "last_event_time_ms":1000,"side":"long","stop_loss":99.8,"tp1":110}
    result = build_trade_alerts(trades=[trade], now_ms=500000)
    assert result["alert_count"] == 0


def test_phase25_reports_database_and_lifecycle_state():
    paper = {"integrity_issue_count":0,"active_trade_count":1}
    alerts = {"alerts":[]}
    result = build_reliability_report(database_probe_ok=True, trades=[{"id":"t1"}],
                                      paper_control=paper, alerts=alerts)
    assert result["status"] == "ok"
    assert result["execution_allowed"] is False


def test_phase25_degrades_on_database_failure():
    result = build_reliability_report(database_probe_ok=False, trades=[],
                                      paper_control={"integrity_issue_count":0},
                                      alerts={"alerts":[]})
    assert result["status"] == "degraded"
