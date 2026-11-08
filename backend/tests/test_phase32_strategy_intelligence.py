import pytest
from app.phase32_strategy_intelligence import evaluate_strategy_candidates


def _candidate(name="Trend Alpha", **overrides):
    data = {
        "name": name, "trade_count": 120, "win_rate_pct": 55,
        "profit_factor": 1.6, "max_drawdown_pct": 5,
        "expectancy_r": 0.35, "suitable_regimes": ["trending"],
    }
    data.update(overrides)
    return data


def test_phase32_ranks_eligible_candidate_first():
    result = evaluate_strategy_candidates(
        market_regime="trending",
        strategies=[_candidate("A", profit_factor=1.2), _candidate("B", profit_factor=1.8)],
    )
    assert result["ranked_strategies"][0]["name"] == "B"
    assert result["ranked_strategies"][0]["eligible_for_consideration"] is True


def test_phase32_regime_compatibility_is_required():
    result = evaluate_strategy_candidates(market_regime="ranging", strategies=[_candidate()])
    item = result["ranked_strategies"][0]
    assert item["eligible_for_consideration"] is False
    assert "regime_compatibility_not_provided" in item["issues"]


def test_phase32_transition_never_marks_candidate_eligible():
    result = evaluate_strategy_candidates(market_regime="transition", strategies=[_candidate()])
    assert result["eligible_candidate_count"] == 0


def test_phase32_insufficient_sample_is_not_eligible():
    result = evaluate_strategy_candidates(market_regime="trending", strategies=[
        _candidate(trade_count=10)
    ])
    assert "sample_below_minimum" in result["ranked_strategies"][0]["issues"]


def test_phase32_drawdown_limit_is_enforced():
    result = evaluate_strategy_candidates(market_regime="trending", strategies=[
        _candidate(max_drawdown_pct=30)
    ], max_drawdown_pct=15)
    assert result["ranked_strategies"][0]["eligible_for_consideration"] is False


def test_phase32_unprofitable_metrics_are_not_eligible():
    result = evaluate_strategy_candidates(market_regime="trending", strategies=[
        _candidate(profit_factor=0.9, expectancy_r=-0.1)
    ])
    assert result["eligible_candidate_count"] == 0


def test_phase32_never_selects_or_changes_allocation():
    result = evaluate_strategy_candidates(market_regime="trending", strategies=[_candidate()])
    assert result["selection"] is None
    assert result["allocation_changes"] == []
    assert result["execution_allowed"] is False


@pytest.mark.parametrize("kwargs", [
    {"market_regime": "chaotic", "strategies": []},
    {"market_regime": "trending", "strategies": [], "minimum_trades": 1},
    {"market_regime": "trending", "strategies": [], "max_drawdown_pct": 0},
    {"market_regime": "trending", "strategies": [_candidate(win_rate_pct=101)]},
    {"market_regime": "trending", "strategies": [_candidate(profit_factor=float("nan"))]},
])
def test_phase32_rejects_invalid_inputs(kwargs):
    with pytest.raises(ValueError):
        evaluate_strategy_candidates(**kwargs)
