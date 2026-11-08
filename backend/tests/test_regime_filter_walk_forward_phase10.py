from __future__ import annotations

import pytest

from app.regime_filter_walk_forward import evaluate_regime_filter_walk_forward


def _data(count=300):
    times = [1_700_000_000 + i * 300 for i in range(count)]
    return {
        "BTCUSDT": {
            "5m": [{"time": t} for t in times],
        }
    }


def test_walk_forward_runs_multiple_expanding_oos_folds(monkeypatch):
    import app.regime_filter_walk_forward as module

    calls = []

    def fake_backtest(data, **kwargs):
        calls.append(kwargs)
        pnl = 12.0 if kwargs["use_regime_filter"] else 10.0
        return {
            "trades": [{"net_pnl": pnl, "market_regime": {"aggregate_regime": "trending"}}],
            "max_drawdown_pct": 1.5,
            "signal_generation": {
                "BTCUSDT": {"rejected_counts": {"regime_filter": 2 if kwargs["use_regime_filter"] else 0}}
            },
        }

    monkeypatch.setattr(module, "run_historical_smc_portfolio_backtest", fake_backtest)
    result = module.evaluate_regime_filter_walk_forward(
        _data(), initial_train_fraction=0.5, oos_fraction=0.1,
        step_fraction=0.1, max_folds=3,
    )
    assert result["fold_count"] == 3
    assert len(calls) == 6
    assert all(calls[i]["signal_time_start"] == calls[i + 1]["signal_time_start"] for i in (0, 2, 4))
    assert all(calls[i]["signal_time_end"] == calls[i + 1]["signal_time_end"] for i in (0, 2, 4))
    assert result["aggregate"]["delta_filtered_minus_baseline"]["net_pnl"] == 6.0


def test_walk_forward_rejects_misaligned_symbol_timestamps():
    data = _data(300)
    data["ETHUSDT"] = {"5m": [{"time": 1_700_000_100 + i * 300} for i in range(300)]}
    with pytest.raises(ValueError, match="identical aligned"):
        evaluate_regime_filter_walk_forward(data)


def test_walk_forward_requires_enough_history_for_two_folds():
    with pytest.raises(ValueError, match="at least two OOS folds"):
        evaluate_regime_filter_walk_forward(
            _data(200), initial_train_fraction=0.8,
            oos_fraction=0.2, step_fraction=0.1, max_folds=5,
        )


def test_walk_forward_validates_fold_count():
    with pytest.raises(ValueError, match="max_folds"):
        evaluate_regime_filter_walk_forward(_data(), max_folds=1)


def test_backtest_replay_window_end_excludes_later_candles():
    from app.historical_smc_backtest import run_historical_smc_portfolio_backtest
    import inspect
    assert "signal_time_end" in inspect.signature(run_historical_smc_portfolio_backtest).parameters
