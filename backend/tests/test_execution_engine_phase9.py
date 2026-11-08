import pytest

from app.execution_engine import (
    validate_execution_plan, entry_triggered, adverse_fill,
    process_trade_tick, cancel_pending_trade,
)


def make_state(**overrides):
    state = {
        "side": "long", "status": "pending_entry", "planned_entry": 100.0,
        "avg_entry_price": None, "stop_loss": 95.0, "initial_stop_loss": 95.0,
        "tp1": 102.0, "tp2": 105.0, "tp3": 108.0,
        "quantity": 1.0, "remaining_quantity": 1.0,
        "tp1_fraction": 0.5, "tp2_fraction": 0.3, "tp3_fraction": 0.2,
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
        "move_stop_to_breakeven_after_tp1": True, "trailing_stop_pct": None,
        "high_water": None, "low_water": None, "commission_pct": 0.0,
        "slippage_bps": 0.0, "realized_pnl": 0.0, "fees_paid": 0.0,
        "last_price": None, "last_event_time_ms": 0,
    }
    state.update(overrides)
    return state


def test_plan_validates_directional_level_order_and_target_fractions():
    result = validate_execution_plan(
        side="long", quantity=1, planned_entry=100, stop_loss=95,
        tp1=102, tp2=105, tp3=108,
    )
    assert result["tp1_fraction"] == pytest.approx(0.5)
    with pytest.raises(ValueError, match="Long plan"):
        validate_execution_plan(side="long", quantity=1, planned_entry=100,
                                stop_loss=101, tp1=102, tp2=105, tp3=108)
    with pytest.raises(ValueError, match="sum to 1"):
        validate_execution_plan(side="long", quantity=1, planned_entry=100,
                                stop_loss=95, tp1=102, tp2=105, tp3=108,
                                target_fractions=(0.5, 0.3, 0.3))


def test_short_plan_requires_descending_targets_below_entry():
    result = validate_execution_plan(side="short", quantity=2, planned_entry=100,
                                     stop_loss=105, tp1=98, tp2=95, tp3=92)
    assert result["side"] == "short"


def test_entry_trigger_and_adverse_slippage_for_both_directions():
    assert entry_triggered("long", 99, 100)
    assert not entry_triggered("long", 101, 100)
    assert entry_triggered("short", 101, 100)
    assert not entry_triggered("short", 99, 100)
    assert adverse_fill(100, "long", True, 10) == pytest.approx(100.1)
    assert adverse_fill(100, "short", True, 10) == pytest.approx(99.9)
    assert adverse_fill(100, "long", False, 10) == pytest.approx(99.9)
    assert adverse_fill(100, "short", False, 10) == pytest.approx(100.1)


def test_pending_entry_waits_then_fills_and_does_not_exit_on_same_tick():
    state, events = process_trade_tick(make_state(), market_price=101,
                                       event_time_ms=1000, event_id="tick-1")
    assert state["status"] == "pending_entry"
    assert events[0]["event_type"] == "PRICE_OBSERVED"
    state, events = process_trade_tick(state, market_price=99,
                                       event_time_ms=2000, event_id="tick-2")
    assert state["status"] == "open"
    assert state["avg_entry_price"] == pytest.approx(99)
    assert [x["event_type"] for x in events] == ["ENTRY_FILLED"]


def test_partial_targets_reduce_remaining_and_move_stop_to_breakeven():
    state, _ = process_trade_tick(make_state(), market_price=99,
                                  event_time_ms=1000, event_id="entry")
    state, events = process_trade_tick(state, market_price=102,
                                       event_time_ms=2000, event_id="tp1")
    assert state["status"] == "partially_closed"
    assert state["remaining_quantity"] == pytest.approx(0.5)
    assert state["realized_pnl"] == pytest.approx(1.5)
    assert state["stop_loss"] == pytest.approx(99)
    assert state["tp1_hit"] is True
    assert "STOP_MOVED_TO_BREAKEVEN" in [x["event_type"] for x in events]


def test_tp2_and_tp3_close_remaining_quantity_exactly():
    state, _ = process_trade_tick(make_state(), market_price=99,
                                  event_time_ms=1000, event_id="entry")
    state, _ = process_trade_tick(state, market_price=102,
                                  event_time_ms=2000, event_id="tp1")
    state, _ = process_trade_tick(state, market_price=105,
                                  event_time_ms=3000, event_id="tp2")
    assert state["remaining_quantity"] == pytest.approx(0.2)
    state, events = process_trade_tick(state, market_price=108,
                                       event_time_ms=4000, event_id="tp3")
    assert state["status"] == "closed"
    assert state["remaining_quantity"] == 0
    assert state["realized_pnl"] == pytest.approx(5.1)
    assert events[0]["event_type"] == "TP3_FILLED"


def test_stop_closes_all_remaining_quantity_and_slippage_is_adverse():
    state, _ = process_trade_tick(make_state(slippage_bps=10), market_price=99,
                                  event_time_ms=1000, event_id="entry")
    state, events = process_trade_tick(state, market_price=94,
                                       event_time_ms=2000, event_id="stop")
    assert state["status"] == "closed"
    assert state["remaining_quantity"] == 0
    assert events[0]["event_type"] == "STOP_FILLED"
    assert events[0]["fill_price"] < 94


def test_trailing_stop_only_tightens_and_tracks_favorable_extreme():
    state, _ = process_trade_tick(make_state(trailing_stop_pct=2), market_price=99,
                                  event_time_ms=1000, event_id="entry")
    state, _ = process_trade_tick(state, market_price=102,
                                  event_time_ms=2000, event_id="tp1")
    assert state["high_water"] == pytest.approx(102)
    first_stop = state["stop_loss"]
    state, _ = process_trade_tick(state, market_price=106,
                                  event_time_ms=3000, event_id="run-up")
    assert state["high_water"] == pytest.approx(106)
    assert state["stop_loss"] > first_stop
    tightened = state["stop_loss"]
    state, _ = process_trade_tick(state, market_price=104,
                                  event_time_ms=4000, event_id="pullback")
    assert state["stop_loss"] == pytest.approx(tightened)


def test_manual_close_uses_adverse_fill_and_closes_trade():
    state, _ = process_trade_tick(make_state(), market_price=99,
                                  event_time_ms=1000, event_id="entry")
    state, events = process_trade_tick(state, market_price=101,
                                       event_time_ms=2000, event_id="manual", force_close=True)
    assert state["status"] == "closed"
    assert events[0]["event_type"] == "MANUAL_CLOSE_FILLED"


def test_cancel_only_applies_to_pending_entry():
    assert cancel_pending_trade(make_state())["status"] == "cancelled"
    with pytest.raises(ValueError, match="Only a pending-entry"):
        cancel_pending_trade(make_state(status="open"))


def test_rejects_stale_events_and_terminal_trade_updates():
    state, _ = process_trade_tick(make_state(), market_price=99,
                                  event_time_ms=1000, event_id="entry")
    with pytest.raises(ValueError, match="chronological"):
        process_trade_tick(state, market_price=98, event_time_ms=1000, event_id="stale")
    state, _ = process_trade_tick(state, market_price=94,
                                  event_time_ms=2000, event_id="stop")
    with pytest.raises(ValueError, match="terminal"):
        process_trade_tick(state, market_price=90, event_time_ms=3000, event_id="after-close")


def test_manual_close_is_rejected_before_pending_entry_fills():
    with pytest.raises(ValueError, match="cannot be closed before it fills"):
        process_trade_tick(make_state(), market_price=99, event_time_ms=1000,
                           event_id="premature-close", force_close=True)
