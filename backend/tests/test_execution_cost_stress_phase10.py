from __future__ import annotations

import pytest

from app.execution_cost_stress import _trade_risk_stats, evaluate_execution_cost_stress


def test_trade_risk_stats_detects_losing_streak_and_drawdown():
    result = _trade_risk_stats([
        {"net_pnl": 10}, {"net_pnl": -5}, {"net_pnl": -7},
        {"net_pnl": -2}, {"net_pnl": 8},
    ])
    assert result["max_consecutive_losses"] == 3
    assert result["max_trade_sequence_drawdown"] == 14
    assert result["gross_profit"] == 18
    assert result["gross_loss"] == 14


def test_stress_evaluation_runs_each_cost_scenario(monkeypatch):
    import app.execution_cost_stress as module

    calls = []

    def fake_backtest(data, **kwargs):
        calls.append(kwargs)
        pnl = 100 - kwargs["spread"] * 10 - kwargs["slippage"] * 5 - kwargs["commission_pct"] * 100
        return {
            "trades": [{"net_pnl": pnl}, {"net_pnl": -20}],
            "max_drawdown_pct": 2.5,
            "generated_signal_count": 4,
            "trade_count": 2,
            "rejected_signals": [],
            "ending_equity": 10_000 + pnl - 20,
        }

    monkeypatch.setattr(module, "run_historical_smc_portfolio_backtest", fake_backtest)
    scenarios = [
        {"name": "base", "spread": 0, "slippage": 0, "commission_pct": 0},
        {"name": "stress", "spread": 1, "slippage": 1, "commission_pct": 0.1},
    ]
    result = module.evaluate_execution_cost_stress(
        {"BTCUSDT": {"5m": []}}, cost_scenarios=scenarios
    )
    assert len(calls) == 2
    assert result["scenario_count"] == 2
    assert result["scenarios"][1]["metrics"]["net_pnl"] < result["scenarios"][0]["metrics"]["net_pnl"]
    assert result["execution_allowed"] is False


@pytest.mark.parametrize("scenarios", [[], [{"name": "one", "spread": 0, "slippage": 0, "commission_pct": 0}]])
def test_rejects_too_few_cost_scenarios(scenarios):
    with pytest.raises(ValueError, match="between 2 and 10"):
        evaluate_execution_cost_stress({"BTCUSDT": {"5m": []}}, cost_scenarios=scenarios)


def test_rejects_negative_or_nonfinite_cost():
    scenarios = [
        {"name": "base", "spread": 0, "slippage": 0, "commission_pct": 0},
        {"name": "bad", "spread": -1, "slippage": 0, "commission_pct": 0},
    ]
    with pytest.raises(ValueError, match="invalid spread"):
        evaluate_execution_cost_stress({"BTCUSDT": {"5m": []}}, cost_scenarios=scenarios)


def test_rejects_duplicate_scenario_names():
    scenarios = [
        {"name": "same", "spread": 0, "slippage": 0, "commission_pct": 0},
        {"name": "same", "spread": 1, "slippage": 0, "commission_pct": 0},
    ]
    with pytest.raises(ValueError, match="unique"):
        evaluate_execution_cost_stress({"BTCUSDT": {"5m": []}}, cost_scenarios=scenarios)
