import pytest

from app.phase31_burn_in import build_burn_in_report

NOW = 1_800_000_000_000


def _sample():
    trade = {
        "id": "t1", "symbol": "BTCUSDT", "status": "closed",
        "quantity": 1.0, "remaining_quantity": 0.0,
        "avg_entry_price": 100.0, "realized_pnl": 10.0, "fees_paid": 1.0,
    }
    events = [
        {"id": 1, "source_event_id": "created", "sequence_no": 0,
         "event_type": "ORDER_CREATED", "event_time_ms": NOW - 3_600_000,
         "pnl": 0.0, "fee": 0.0, "quantity": 1.0},
        {"id": 2, "source_event_id": "entry", "sequence_no": 0,
         "event_type": "ENTRY_FILLED", "event_time_ms": NOW - 1_800_000,
         "pnl": 0.0, "fee": 0.4, "quantity": 1.0},
        {"id": 3, "source_event_id": "exit", "sequence_no": 0,
         "event_type": "TP3_FILLED", "event_time_ms": NOW - 600_000,
         "pnl": 10.0, "fee": 0.6, "quantity": 1.0},
    ]
    return [trade], {"t1": events}


def test_phase31_passes_valid_burn_in_sample():
    trades, events = _sample()
    result = build_burn_in_report(
        trades=trades, events_by_trade=events, now_ms=NOW,
        window_hours=24, minimum_events=3, minimum_observation_minutes=30,
    )
    assert result["status"] == "passed"
    assert result["realized_net_pnl"] == 9.0
    assert result["window_event_count"] == 3
    assert result["execution_allowed"] is False


def test_phase31_detects_realized_pnl_mismatch():
    trades, events = _sample()
    trades[0]["realized_pnl"] = 12.0
    result = build_burn_in_report(
        trades=trades, events_by_trade=events, now_ms=NOW,
        minimum_events=1, minimum_observation_minutes=1,
    )
    assert result["status"] == "review_required"
    assert "realized_pnl_journal_mismatch" in {x["code"] for x in result["issues"]}


def test_phase31_detects_fee_mismatch():
    trades, events = _sample()
    trades[0]["fees_paid"] = 0.5
    result = build_burn_in_report(
        trades=trades, events_by_trade=events, now_ms=NOW,
        minimum_events=1, minimum_observation_minutes=1,
    )
    assert "fees_journal_mismatch" in {x["code"] for x in result["issues"]}


def test_phase31_detects_exit_quantity_mismatch():
    trades, events = _sample()
    events["t1"][-1]["quantity"] = 0.8
    result = build_burn_in_report(
        trades=trades, events_by_trade=events, now_ms=NOW,
        minimum_events=1, minimum_observation_minutes=1,
    )
    assert "exit_quantity_journal_mismatch" in {x["code"] for x in result["issues"]}


def test_phase31_flags_stale_active_trade():
    trades, events = _sample()
    trades[0].update({"status": "open", "remaining_quantity": 1.0, "realized_pnl": 0.0, "fees_paid": 0.0,
                      "avg_entry_price": 100.0})
    events["t1"] = [{
        "id": 1, "source_event_id": "created", "sequence_no": 0,
        "event_type": "ORDER_CREATED", "event_time_ms": NOW - 900_000,
        "pnl": 0.0, "fee": 0.0, "quantity": 1.0,
    }]
    result = build_burn_in_report(
        trades=trades, events_by_trade=events, now_ms=NOW,
        stale_after_seconds=300, minimum_events=1, minimum_observation_minutes=1,
    )
    assert result["status"] == "degraded"
    assert result["stale_active_trade_ids"] == ["t1"]


def test_phase31_reports_insufficient_activity_for_empty_portfolio():
    result = build_burn_in_report(trades=[], events_by_trade={}, now_ms=NOW)
    assert result["status"] == "insufficient_activity"


def test_phase31_reports_insufficient_observation():
    trades, events = _sample()
    result = build_burn_in_report(
        trades=trades, events_by_trade=events, now_ms=NOW,
        minimum_events=10, minimum_observation_minutes=30,
    )
    assert result["status"] == "insufficient_observation"


@pytest.mark.parametrize("kwargs", [
    {"window_hours": 0},
    {"window_hours": 721},
    {"stale_after_seconds": 1},
    {"minimum_events": 0},
    {"minimum_observation_minutes": 0},
])
def test_phase31_rejects_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        build_burn_in_report(trades=[], events_by_trade={}, now_ms=NOW, **kwargs)
