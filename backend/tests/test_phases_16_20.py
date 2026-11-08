from contextlib import contextmanager

import pytest

from app.historical_optimizer import optimize_historical_smc
from app.strategy_portfolio_intelligence import allocate_strategy_weights
from app.production_observability import build_operational_report
from app.security_release_audit import build_security_audit, build_release_audit


def candles():
    rows = [{"time": 1_700_000_000 + i * 300, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1} for i in range(120)]
    return {"BTCUSDT": {"5m": rows, "15m": rows[::3], "1h": rows[::12], "4h": rows[::48]}}


def test_phase16_selects_on_train_then_runs_oos_once():
    calls = []
    def runner(**kwargs):
        calls.append(kwargs)
        is_oos = kwargs.get("signal_time_start") is not None
        return {"trade_count": 12 if not is_oos else 7, "net_pnl": 120 if not is_oos else 35,
                "expectancy_per_trade": 10 if not is_oos else 5,
                "profit_factor": 1.5, "win_rate_pct": 60, "max_drawdown_pct": 4,
                "execution_allowed": False}
    result = optimize_historical_smc(candles_by_symbol_and_tf=candles(), runner=runner,
                                     min_quality_scores=[60, 65], min_rr_values=[2],
                                     min_train_trades=5)
    assert result["status"] == "completed"
    assert result["out_of_sample"]["trade_count"] == 7
    assert len(calls) == 3  # two train candidates + one OOS evaluation
    assert result["execution_allowed"] is False


def test_phase16_rejects_oversized_grid():
    with pytest.raises(ValueError):
        optimize_historical_smc(candles_by_symbol_and_tf=candles(), runner=lambda **_: {},
                                min_quality_scores=[50, 55, 60, 65, 70],
                                min_rr_values=[1, 1.5, 2, 2.5, 3], max_combinations=24)


def test_phase17_weights_respect_caps_and_cash_reserve():
    result = allocate_strategy_weights(strategies=[
        {"name": "A", "expectancy_r": 0.3, "risk_r": 1},
        {"name": "B", "expectancy_r": 0.2, "risk_r": 1},
        {"name": "C", "expectancy_r": -0.1, "risk_r": 1},
    ], max_weight=0.4)
    assert result["allocated_pct"] <= 80.0001
    assert result["cash_reserve_pct"] >= 19.999
    assert all(x["weight_pct"] <= 40 for x in result["allocations"])


def test_phase17_rejects_asymmetric_correlation():
    with pytest.raises(ValueError):
        allocate_strategy_weights(strategies=[{"name":"A","expectancy_r":1,"risk_r":1},
                                                {"name":"B","expectancy_r":1,"risk_r":1}],
                                  correlation=[[1, .2], [.4, 1]])


def test_phase18_operational_probe_and_phase19_security_guard():
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, query): return 1
    report = build_operational_report(session_factory=lambda: Session())
    assert report["status"] == "ok"
    sec = build_security_audit(authenticated_user={"id":"u1"}, portfolio={"id":"p1"})
    assert sec["status"] == "passed"
    assert sec["execution_allowed"] is False


def test_phase20_never_certifies_live_readiness():
    ok = {"status":"completed"}
    result = build_release_audit(performance=ok, validation=ok, walk_forward=ok,
                                 research_audit=ok, security_audit=ok,
                                 operational_report={"status":"ok"})
    assert result["status"] == "research_checks_passed"
    assert result["execution_allowed"] is False
    assert "live trading" in " ".join(result["limitations"]).lower()
