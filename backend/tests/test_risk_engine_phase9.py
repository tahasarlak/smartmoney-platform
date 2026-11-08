from __future__ import annotations

import math
import pytest
from app.risk_engine import (
    calculate_risk_position_size, calculate_correlation_matrix,
    assess_portfolio_risk, allocate_capital,
)


def test_position_size_respects_risk_and_notional_caps():
    result = calculate_risk_position_size(
        equity=10_000, risk_pct=1, entry=100, stop=95, max_notional_pct=20
    )
    assert result["quantity"] == pytest.approx(20)
    assert result["risk_cash"] == pytest.approx(100)
    assert result["notional_pct"] == pytest.approx(20)
    assert result["capped_by_notional"] is False
    assert result["execution_allowed"] is False


def test_position_size_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        calculate_risk_position_size(equity=1000, risk_pct=1, entry=100, stop=100)
    with pytest.raises(ValueError):
        calculate_risk_position_size(equity=float("nan"), risk_pct=1, entry=100, stop=90)


def test_correlation_uses_returns_and_detects_perfect_positive_relationship():
    result = calculate_correlation_matrix({
        "BTCUSDT": [100, 101, 102, 104, 103, 105],
        "ETHUSDT": [200, 202, 204, 208, 206, 210],
    }, min_observations=3)
    assert result["matrix"]["BTCUSDT"]["ETHUSDT"] == pytest.approx(1.0)
    assert result["return_observations"] == 5


def test_correlation_rejects_misaligned_or_insufficient_series():
    with pytest.raises(ValueError, match="aligned"):
        calculate_correlation_matrix({"A": [1, 2, 3, 4], "B": [1, 2, 3]})
    with pytest.raises(ValueError, match="required"):
        calculate_correlation_matrix({"A": [1, 2, 3], "B": [2, 3, 4]}, min_observations=5)


def test_correlation_returns_none_for_constant_return_series():
    result = calculate_correlation_matrix({
        "A": [10, 10, 10, 10, 10], "B": [1, 2, 1, 2, 1]
    }, min_observations=3)
    assert result["matrix"]["A"]["B"] is None


def test_portfolio_assessment_aggregates_symbol_direction_and_exposure():
    report = assess_portfolio_risk(
        equity=10_000,
        positions=[
            {"symbol": "BTCUSDT", "side": "long", "quantity": 1, "entry": 100, "stop": 90, "risk_cash": 10},
            {"symbol": "ETHUSDT", "side": "long", "quantity": 2, "entry": 50, "stop": 45, "risk_cash": 10},
        ],
        max_portfolio_risk_pct=3, max_trade_risk_pct=1, max_open_trades=3,
    )
    assert report["total_open_risk_cash"] == 20
    assert report["total_open_risk_pct"] == pytest.approx(0.2)
    assert report["risk_by_direction"]["long"]["risk_cash"] == 20
    assert report["gross_notional"] == 200
    assert report["status"] == "healthy"


def test_portfolio_assessment_blocks_when_aggregate_limit_is_exceeded():
    report = assess_portfolio_risk(
        equity=1000,
        positions=[{"symbol": "BTC", "side": "long", "quantity": 2, "entry": 100, "stop": 90, "risk_cash": 25}],
        max_portfolio_risk_pct=2, max_trade_risk_pct=1, max_open_trades=3,
    )
    assert report["status"] == "blocked"
    assert "aggregate_open_risk_exceeds_configured_limit" in report["blockers"]


def test_allocator_respects_trade_cap_budget_and_slot_limit():
    result = allocate_capital(
        equity=10_000,
        candidates=[
            {"symbol": "BTCUSDT", "direction": "long", "entry": 100, "stop": 95, "quality_score": 90},
            {"symbol": "ETHUSDT", "direction": "short", "entry": 50, "stop": 52, "quality_score": 70},
            {"symbol": "SOLUSDT", "direction": "long", "entry": 20, "stop": 19, "quality_score": 60},
        ],
        current_open_risk_cash=50, max_portfolio_risk_pct=3,
        max_trade_risk_pct=1, max_open_trades=2, current_open_positions=1,
    )
    assert len(result["allocations"]) == 1
    assert result["allocations"][0]["symbol"] == "BTCUSDT"
    assert result["allocations"][0]["risk_cash"] <= 100
    assert result["execution_allowed"] is False


def test_allocator_rejects_wrong_side_stop_and_duplicate_candidates():
    base = dict(equity=1000, current_open_risk_cash=0, max_portfolio_risk_pct=3,
                max_trade_risk_pct=1, max_open_trades=3, current_open_positions=0)
    with pytest.raises(ValueError, match="wrong side"):
        allocate_capital(**base, candidates=[{"symbol":"BTC", "direction":"long", "entry":100, "stop":101, "quality_score":80}])
    with pytest.raises(ValueError, match="Duplicate"):
        allocate_capital(**base, candidates=[
            {"symbol":"BTC", "direction":"long", "entry":100, "stop":90, "quality_score":80},
            {"symbol":"BTC", "direction":"long", "entry":100, "stop":91, "quality_score":70},
        ])


def test_phase8_authenticated_api_routes_are_registered_without_database_access():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "app" / "v11_platform.py").read_text(encoding="utf-8")
    assert '"/risk/position-size"' in source
    assert '"/risk/correlation"' in source
    assert '"/portfolios/{portfolio_id}/risk"' in source
    assert '"/portfolios/{portfolio_id}/risk/allocate"' in source


def test_correlation_adjusted_allocator_penalizes_same_direction_crowding():
    from app.risk_engine import allocate_capital_with_correlation

    prices_a = [100, 101, 103, 102, 105, 107, 106, 110, 112, 111, 115, 118]
    prices_b = [200, 202, 206, 204, 210, 214, 212, 220, 224, 222, 230, 236]
    prices_c = [50, 51, 49, 52, 48, 50, 47, 51, 49, 52, 48, 50]
    result = allocate_capital_with_correlation(
        equity=10_000,
        candidates=[
            {"symbol":"AAA", "direction":"long", "entry":100, "stop":95, "quality_score":90},
            {"symbol":"BBB", "direction":"long", "entry":200, "stop":190, "quality_score":90},
            {"symbol":"CCC", "direction":"long", "entry":50, "stop":47, "quality_score":90},
        ],
        prices_by_symbol={"AAA":prices_a,"BBB":prices_b,"CCC":prices_c},
        current_open_risk_cash=0, max_portfolio_risk_pct=3,
        max_trade_risk_pct=1, max_open_trades=3, current_open_positions=0,
        min_observations=5,
    )
    allocations = {x["symbol"]:x for x in result["allocations"]}
    assert allocations["AAA"]["correlation_penalty_factor"] > 1
    assert allocations["BBB"]["correlation_penalty_factor"] > 1
    assert allocations["AAA"]["adjusted_allocation_score"] < 90
    assert result["execution_allowed"] is False
    assert result["correlation"]["direction_adjusted"] is True


def test_correlation_adjusted_allocator_accounts_for_long_short_direction():
    from app.risk_engine import allocate_capital_with_correlation

    a = [100, 101, 103, 102, 105, 107, 106, 110, 112, 111, 115, 118]
    b = [200, 202, 206, 204, 210, 214, 212, 220, 224, 222, 230, 236]
    result = allocate_capital_with_correlation(
        equity=10_000,
        candidates=[
            {"symbol":"AAA", "direction":"long", "entry":100, "stop":95, "quality_score":80},
            {"symbol":"BBB", "direction":"short", "entry":200, "stop":205, "quality_score":80},
        ],
        prices_by_symbol={"AAA":a,"BBB":b},
        current_open_risk_cash=0, max_portfolio_risk_pct=3,
        max_trade_risk_pct=1, max_open_trades=2, current_open_positions=0,
        min_observations=5,
    )
    diagnostics = result["candidate_diagnostics"]
    assert diagnostics["AAA"]["positive_correlation_crowding"] == 0
    assert diagnostics["BBB"]["positive_correlation_crowding"] == 0


def test_correlation_adjusted_allocator_rejects_missing_or_unaligned_market_data():
    from app.risk_engine import allocate_capital_with_correlation

    base = dict(
        equity=10_000,
        candidates=[
            {"symbol":"AAA", "direction":"long", "entry":100, "stop":95, "quality_score":80},
            {"symbol":"BBB", "direction":"long", "entry":200, "stop":190, "quality_score":70},
        ],
        current_open_risk_cash=0, max_portfolio_risk_pct=3,
        max_trade_risk_pct=1, max_open_trades=2, current_open_positions=0,
        min_observations=3,
    )
    with pytest.raises(ValueError, match="Missing price history"):
        allocate_capital_with_correlation(**base, prices_by_symbol={"AAA":[1,2,3,4]})
    with pytest.raises(ValueError, match="aligned"):
        allocate_capital_with_correlation(**base, prices_by_symbol={
            "AAA":[1,2,3,4,5], "BBB":[1,2,3,4]
        })


def test_phase9_correlation_aware_allocation_route_is_registered():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "app" / "v11_platform.py").read_text(encoding="utf-8")
    assert '@router.post("/portfolios/{portfolio_id}/risk/allocate-correlated")' in source
    assert "def api_portfolio_risk_allocate_correlated(" in source
