from __future__ import annotations

import pytest

from app.regime_filter_evaluation import _metrics, _regime_breakdown, evaluate_regime_filter_oos


def test_metrics_calculate_profit_factor_and_expectancy():
    result = _metrics([
        {"net_pnl": 20}, {"net_pnl": -10}, {"net_pnl": 10}, {"net_pnl": -5}
    ])
    assert result["trade_count"] == 4
    assert result["win_rate_pct"] == 50.0
    assert result["net_pnl"] == 15.0
    assert result["profit_factor"] == 2.0
    assert result["expectancy_per_trade"] == 3.75


def test_metrics_handle_no_losses_without_division_error():
    result = _metrics([{"net_pnl": 5}, {"net_pnl": 10}])
    assert result["profit_factor"] == "infinite"


def test_regime_breakdown_groups_trade_results():
    trades = [
        {"net_pnl": 10, "market_regime": {"aggregate_regime": "trending"}},
        {"net_pnl": -5, "market_regime": {"aggregate_regime": "ranging"}},
        {"net_pnl": 5, "market_regime": {"aggregate_regime": "trending"}},
    ]
    result = _regime_breakdown(trades)
    assert result["trending"]["trade_count"] == 2
    assert result["trending"]["net_pnl"] == 15
    assert result["ranging"]["trade_count"] == 1


def test_evaluation_rejects_short_history():
    with pytest.raises(ValueError, match="At least 100 5m candles"):
        evaluate_regime_filter_oos({"BTCUSDT": {"5m": [{"time": i} for i in range(20)]}})


def test_evaluation_rejects_unaligned_symbol_cutoffs():
    rows_a = [{"time": 1_700_000_000 + i * 300} for i in range(120)]
    rows_b = [{"time": 1_700_000_100 + i * 300} for i in range(120)]
    data = {
        "BTCUSDT": {"5m": rows_a},
        "ETHUSDT": {"5m": rows_b},
    }
    with pytest.raises(ValueError, match="share the same 5m OOS cutoff"):
        evaluate_regime_filter_oos(data)


def test_evaluation_runs_baseline_and_filtered_on_same_oos_cutoff(monkeypatch):
    import app.regime_filter_evaluation as module

    calls = []

    def fake_backtest(data, **kwargs):
        calls.append(kwargs)
        trades = [{
            "net_pnl": 10 if not kwargs["use_regime_filter"] else 12,
            "market_regime": {"aggregate_regime": "trending"},
        }]
        return {
            "trades": trades,
            "generated_signal_count": 1,
            "max_drawdown_pct": 2.0,
            "rejected_signals": [],
            "signal_generation": {
                "BTCUSDT": {"rejected_counts": {"regime_filter": 1 if kwargs["use_regime_filter"] else 0}}
            },
        }

    monkeypatch.setattr(module, "run_historical_smc_portfolio_backtest", fake_backtest)
    rows = [{"time": 1_700_000_000 + i * 300} for i in range(120)]
    result = module.evaluate_regime_filter_oos({"BTCUSDT": {"5m": rows}})
    assert len(calls) == 2
    assert calls[0]["signal_time_start"] == calls[1]["signal_time_start"]
    assert calls[0]["use_regime_filter"] is False
    assert calls[1]["use_regime_filter"] is True
    assert result["delta_filtered_minus_baseline"]["net_pnl"] == 2
    assert result["regime_filtered"]["filter_rejections"] == 1
