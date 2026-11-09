import pytest
from app.strategy_validation import validate_strategy_walk_forward


def candles(start, count=60, base=100):
    return [
        {"time": start + i * 60, "open": base, "high": base + 20,
         "low": base - 2, "close": base + 1}
        for i in range(count)
    ]


def signals_for(symbol, rows):
    # Stop is below entry and target is reached on the next candle.
    return [
        {"symbol": symbol, "index": i, "direction": "bullish",
         "stop_loss": 90, "take_profit": 110, "quantity": 1}
        for i in range(1, len(rows) - 2, 2)
    ]


def test_walk_forward_returns_chronological_oos_folds_and_no_probability():
    rows = candles(1_800_000_000)
    result = validate_strategy_walk_forward(
        {"BTCUSDT": rows}, signals_for("BTCUSDT", rows), folds=3,
        monte_carlo_simulations=100, initial_equity=10_000,
    )
    assert result["validation_type"] == "rolling_walk_forward_oos_replay"
    assert len(result["folds"]) == 3
    assert result["execution_allowed"] is False
    assert result["estimated_win_probability"] is None
    assert result["methodology"]["optimization"].startswith("Parameter optimization is not performed")
    assert result["aggregate_oos"]["trade_count"] > 0


def test_monte_carlo_is_deterministic_for_same_seed():
    rows = candles(1_800_000_000)
    kwargs = dict(candles_by_symbol={"BTCUSDT": rows}, signals=signals_for("BTCUSDT", rows),
                  folds=3, monte_carlo_simulations=100, random_seed=17)
    a = validate_strategy_walk_forward(**kwargs)
    b = validate_strategy_walk_forward(**kwargs)
    assert a["monte_carlo"] == b["monte_carlo"]


def test_walk_forward_rejects_invalid_fold_count():
    rows = candles(1_800_000_000)
    with pytest.raises(ValueError, match="folds"):
        validate_strategy_walk_forward({"BTCUSDT": rows}, [], folds=1)


def test_walk_forward_does_not_claim_monte_carlo_from_too_few_trades():
    rows = candles(1_800_000_000, 20)
    result = validate_strategy_walk_forward(
        {"BTCUSDT": rows}, signals_for("BTCUSDT", rows)[:2], folds=2,
        monte_carlo_simulations=100,
    )
    assert result["monte_carlo"]["status"] == "insufficient_data"


def test_cost_stress_is_reported_and_does_not_enable_execution():
    rows = candles(1_800_000_000)
    result = validate_strategy_walk_forward(
        {"BTCUSDT": rows}, signals_for("BTCUSDT", rows), folds=3,
        monte_carlo_simulations=100, spread=0.1, slippage=0.1,
        commission_pct=0.01,
    )
    assert result["execution_cost_stress"]["cost_multiplier"] == 2
    assert result["execution_allowed"] is False


def test_validation_endpoint_is_registered_without_database_access():
    from app.main import app
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/backtest/validate" in paths



def test_aggregate_drawdown_is_not_fabricated_across_independent_folds():
    rows = candles(1_800_000_000)
    result = validate_strategy_walk_forward(
        {"BTCUSDT": rows}, signals_for("BTCUSDT", rows), folds=3,
        monte_carlo_simulations=100,
    )
    aggregate = result["aggregate_oos"]
    assert aggregate["trade_sequence_max_drawdown_pct"] is None
    assert aggregate["drawdown_scope"] == "not_aggregated_across_independent_folds"


def test_stress_replay_uses_independent_fold_runs():
    rows = candles(1_800_000_000)
    result = validate_strategy_walk_forward(
        {"BTCUSDT": rows}, signals_for("BTCUSDT", rows), folds=3,
        monte_carlo_simulations=100, spread=0.1, slippage=0.1,
        commission_pct=0.01,
    )
    stress = result["execution_cost_stress"]
    assert stress["fold_execution_count"] == result["aggregate_oos"]["completed_test_folds"]
    assert len(stress["folds"]) == stress["fold_execution_count"]
    assert "worst_fold_max_drawdown_pct" in stress


def test_empty_folds_remain_in_positive_fold_ratio_denominator():
    rows = candles(1_800_000_000)
    # All signals are confined to the first part of the series, so at least
    # one later OOS fold has no signals and must remain in the denominator.
    early_signals = [
        {"symbol": "BTCUSDT", "index": i, "direction": "bullish",
         "stop_loss": 90, "take_profit": 110, "quantity": 1}
        for i in range(1, 8, 2)
    ]
    result = validate_strategy_walk_forward(
        {"BTCUSDT": rows}, early_signals, folds=3,
        monte_carlo_simulations=100,
    )
    assert result["aggregate_oos"]["requested_test_folds"] == 3
    assert result["aggregate_oos"]["positive_fold_ratio_pct"] <= (
        result["aggregate_oos"]["positive_test_folds"] / 3 * 100
    )

