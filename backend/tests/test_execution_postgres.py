from __future__ import annotations
import uuid
import pytest
from sqlalchemy import delete
from app import v11_platform as v11
from app.database import session_scope
from app.db_models import Portfolio, User


@pytest.fixture
def phase9_user():
    user = v11.register_user(f"phase9-{uuid.uuid4().hex[:14]}@example.com", "phase-nine-test-password")
    try:
        yield user
    finally:
        with session_scope() as db:
            db.execute(delete(User).where(User.id == user["id"]))


def make_plan(user, key=None):
    account = v11.create_broker_account(user["id"], user["default_portfolio_id"], "binance", "Phase 9 paper")
    payload = v11.ExecutionTradeCreateRequest(
        portfolio_id=user["default_portfolio_id"], account_id=account["id"],
        idempotency_key=key or f"phase9-{uuid.uuid4().hex}", symbol="BTCUSDT",
        side="long", quantity=1, planned_entry=100, stop_loss=95,
        tp1=102, tp2=105, tp3=108, commission_pct=0, slippage_bps=0,
    )
    return account, payload


def test_paper_execution_persists_entry_partial_exit_break_even_and_stop(phase9_user):
    user_id = phase9_user["id"]
    account, payload = make_plan(phase9_user)
    created = v11.create_execution_trade(user_id, payload)
    assert created["status"] == "pending_entry"
    assert created["mode"] == "paper" and created["execution_allowed"] is False

    entry = v11.process_execution_tick(user_id, created["id"],
        v11.ExecutionTickRequest(event_id="p9-entry", market_price=99, event_time_ms=1_900_000_000_000))
    assert entry["status"] == "open"
    assert entry["avg_entry_price"] == pytest.approx(99)

    tp1 = v11.process_execution_tick(user_id, created["id"],
        v11.ExecutionTickRequest(event_id="p9-tp1", market_price=102, event_time_ms=1_900_000_001_000))
    assert tp1["status"] == "partially_closed"
    assert tp1["remaining_quantity"] == pytest.approx(0.5)
    assert tp1["stop_loss"] == pytest.approx(99)

    stopped = v11.process_execution_tick(user_id, created["id"],
        v11.ExecutionTickRequest(event_id="p9-stop", market_price=99, event_time_ms=1_900_000_002_000))
    assert stopped["status"] == "closed"
    assert stopped["remaining_quantity"] == 0
    assert stopped["realized_pnl"] == pytest.approx(1.5)

    events = v11.list_execution_events(user_id, created["id"])
    assert [e["event_type"] for e in events] == [
        "ORDER_CREATED", "ENTRY_FILLED", "TP1_FILLED", "STOP_MOVED_TO_BREAKEVEN", "STOP_FILLED"
    ]


def test_execution_idempotency_prevents_duplicate_order_and_tick(phase9_user):
    user_id = phase9_user["id"]
    _, payload = make_plan(phase9_user, "phase9-idempotency-key")
    first = v11.create_execution_trade(user_id, payload)
    replay = v11.create_execution_trade(user_id, payload)
    assert replay["id"] == first["id"]
    assert replay["idempotent_replay"] is True
    changed = payload.model_copy(update={"quantity": 0.5})
    with pytest.raises(ValueError, match="different execution request"):
        v11.create_execution_trade(user_id, changed)

    tick = v11.ExecutionTickRequest(event_id="same-market-event", market_price=99, event_time_ms=1_900_000_000_000)
    first_tick = v11.process_execution_tick(user_id, first["id"], tick)
    replay_tick = v11.process_execution_tick(user_id, first["id"], tick)
    assert first_tick["status"] == "open"
    assert replay_tick["idempotent_replay"] is True
    assert len(v11.list_execution_events(user_id, first["id"])) == 2


def test_execution_is_tenant_scoped_and_cancel_only_pending(phase9_user):
    user_id = phase9_user["id"]
    _, payload = make_plan(phase9_user)
    trade = v11.create_execution_trade(user_id, payload)
    other = v11.register_user(f"phase9-other-{uuid.uuid4().hex[:10]}@example.com", "phase-nine-test-password")
    try:
        with pytest.raises(LookupError):
            v11.get_execution_trade(other["id"], trade["id"])
        cancelled = v11.cancel_execution_trade(user_id, trade["id"], "cancel-unique-1")
        assert cancelled["status"] == "cancelled"
        with pytest.raises(ValueError, match="pending-entry"):
            v11.cancel_execution_trade(user_id, trade["id"], "cancel-unique-2")
    finally:
        with session_scope() as db:
            db.execute(delete(User).where(User.id == other["id"]))


def test_execution_routes_are_registered_and_risk_snapshot_includes_execution(phase9_user):
    from app.main import app
    paths = {route.path for route in app.routes}
    assert "/api/v1/v11/execution/paper/trades" in paths
    assert "/api/v1/v11/execution/paper/trades/{trade_id}/ticks" in paths
    _, payload = make_plan(phase9_user)
    trade = v11.create_execution_trade(phase9_user["id"], payload)
    snapshot = v11._portfolio_risk_inputs(phase9_user["id"], phase9_user["default_portfolio_id"])
    assert snapshot["execution_position_count"] == 1
    assert any(x["source"] == "paper_execution" for x in snapshot["positions"])


def test_live_binance_market_event_drives_matching_paper_execution(phase9_user):
    user_id = phase9_user["id"]
    _, payload = make_plan(phase9_user)
    trade = v11.create_execution_trade(user_id, payload)
    processed = v11.process_active_execution_market_event({
        "symbol": "BTCUSDT", "price": 99.0, "event_time_ms": 1_900_000_000_000,
        "event_id": "binance-public-trade-9",
    })
    assert processed == 1
    updated = v11.get_execution_trade(user_id, trade["id"])
    assert updated["status"] == "open"
    assert updated["avg_entry_price"] == pytest.approx(99.0)
    assert v11.active_execution_symbols() == ["BTCUSDT"]

def test_partial_realized_execution_pnl_is_included_in_portfolio_equity(phase9_user):
    user_id = phase9_user["id"]
    _, payload = make_plan(phase9_user)
    created = v11.create_execution_trade(user_id, payload)

    v11.process_execution_tick(user_id, created["id"],
        v11.ExecutionTickRequest(event_id="partial-equity-entry", market_price=99, event_time_ms=1_900_000_100_000))
    partial = v11.process_execution_tick(user_id, created["id"],
        v11.ExecutionTickRequest(event_id="partial-equity-tp1", market_price=102, event_time_ms=1_900_000_101_000))
    assert partial["status"] == "partially_closed"
    assert partial["net_realized_pnl"] == pytest.approx(1.5)

    with session_scope() as db:
        portfolio = db.get(Portfolio, phase9_user["default_portfolio_id"])
        summary = v11._portfolio_dict(db, portfolio)
        initial_equity = float(portfolio.initial_equity)

    assert summary["realized_pnl"] == pytest.approx(1.5)
    assert summary["cash_equity"] == pytest.approx(initial_equity + 1.5)

    risk_snapshot = v11._portfolio_risk_inputs(user_id, phase9_user["default_portfolio_id"])
    assert risk_snapshot["equity"] == pytest.approx(initial_equity + 1.5)

