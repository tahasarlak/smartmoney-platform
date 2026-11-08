from app.walk_forward_validation import build_walk_forward_validation
import pytest


def trade(i, r=0.5, status="closed"):
    # initial risk = abs(100 - 90) * 1 = 10; net pnl = r * 10
    return {
        "id": str(i), "status": status, "planned_entry": 100,
        "initial_stop_loss": 90, "quantity": 1,
        "net_realized_pnl": r * 10,
        "closed_at_ms": 1_700_000_000_000 + i * 86_400_000,
    }


def test_chronological_walk_forward_has_future_test_folds():
    rows = [trade(i, 0.2 if i % 3 else -0.1) for i in range(40)]
    result = build_walk_forward_validation(trades=rows, folds=4)
    assert result["valid_closed_trade_count"] == 40
    assert result["completed_folds"] == 4
    assert result["out_of_sample_trade_count"] == 20
    assert result["folds"][0]["train"]["trade_count"] == 20
    assert result["folds"][0]["out_of_sample"]["trade_count"] == 5


def test_sorting_is_chronological_even_when_input_is_reversed():
    rows = [trade(i, 1 if i >= 20 else -1) for i in reversed(range(40))]
    result = build_walk_forward_validation(trades=rows)
    assert result["folds"][0]["test_start"] < result["folds"][-1]["test_start"]


def test_open_and_invalid_risk_trades_are_skipped():
    rows = [trade(1), trade(2, status="open"), {**trade(3), "initial_stop_loss": 100}]
    result = build_walk_forward_validation(trades=rows)
    assert result["valid_closed_trade_count"] == 1
    assert result["skipped_trade_count"] == 2
    assert result["status"] == "insufficient_sample"


def test_insufficient_sample_does_not_claim_success():
    result = build_walk_forward_validation(trades=[trade(i) for i in range(12)])
    assert result["status"] == "insufficient_sample"
    assert result["sample_quality"] == "insufficient"


def test_mixed_out_of_sample_folds_are_reported():
    rows = [trade(i, 0.5 if i < 20 else (-0.4 if i % 2 else 0.2)) for i in range(40)]
    result = build_walk_forward_validation(trades=rows)
    assert result["out_of_sample_trade_count"] == 20
    assert result["status"] in {"mixed_oos", "oos_not_positive", "oos_positive_across_folds"}


def test_invalid_fold_count_rejected():
    with pytest.raises(ValueError):
        build_walk_forward_validation(trades=[trade(i) for i in range(40)], folds=1)


def test_no_live_execution():
    result = build_walk_forward_validation(trades=[trade(i) for i in range(40)])
    assert result["execution_allowed"] is False
