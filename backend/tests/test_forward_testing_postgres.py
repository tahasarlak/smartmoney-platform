from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from app import v11_platform as v11
from app.forward_testing import (
    forward_summary, list_forward_events, list_forward_trades,
    process_forward_tick, start_forward_run, stop_forward_run,
)
from app.database import session_scope
from app.db_models import User
from app.signal_journal import create_signal


@pytest.fixture
def test_user():
    user = v11.register_user(
        f"phase7-{uuid.uuid4().hex[:14]}@example.com",
        "phase-seven-test-password",
    )
    try:
        yield user
    finally:
        with session_scope() as db:
            db.execute(delete(User).where(User.id == user["id"]))


def test_forward_run_imports_signal_fills_entry_partials_and_closes(test_user):
    user_id = test_user["id"]
    portfolio_id = test_user["default_portfolio_id"]
    account = v11.create_broker_account(user_id, portfolio_id, "binance", "Phase 7 paper")
    signal = create_signal({
        "status": "zone_active",
        "execution_allowed": False,
        "symbol": "BTCUSDT",
        "direction": "bullish",
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profits": [
            {"name": "TP1", "price": 102.0},
            {"name": "TP2", "price": 105.0},
            {"name": "TP3", "price": 108.0},
        ],
        "quality_score": 85,
        "current_price": 101.0,
        "zone": {"low": 99.0, "high": 100.0},
        "minimum_rr_requested": 1.5,
        "risk_percent_setting": 0.5,
    }, user_id=user_id, visibility="private")
    run = start_forward_run(
        user_id, portfolio_id, account["id"], ["btcusdt"],
        risk_per_trade_pct=0.5, min_quality_score=70,
        commission_pct=0.0, slippage_bps=0.0,
        include_existing_signals=True,
    )
    tick_base = 1_900_000_000_000
    process_forward_tick({
        "symbol": "BTCUSDT", "price": 99.0,
        "event_time_ms": tick_base, "event_id": "p7-entry",
    })
    trades = list_forward_trades(user_id, run["id"])
    assert len(trades) == 1
    assert trades[0]["signal_id"] == signal["id"]
    assert trades[0]["status"] == "open"
    assert trades[0]["actual_entry"] == pytest.approx(99.0)
    stopping = stop_forward_run(user_id, run["id"])
    assert stopping["status"] == "stopping"

    process_forward_tick({
        "symbol": "BTCUSDT", "price": 102.0,
        "event_time_ms": tick_base + 1000, "event_id": "p7-tp1",
    })
    assert list_forward_trades(user_id, run["id"])[0]["status"] == "tp1_hit"

    process_forward_tick({
        "symbol": "BTCUSDT", "price": 105.0,
        "event_time_ms": tick_base + 2000, "event_id": "p7-tp2",
    })
    assert list_forward_trades(user_id, run["id"])[0]["status"] == "tp2_hit"

    process_forward_tick({
        "symbol": "BTCUSDT", "price": 108.0,
        "event_time_ms": tick_base + 3000, "event_id": "p7-tp3",
    })
    trade = list_forward_trades(user_id, run["id"])[0]
    assert trade["status"] == "tp3_hit"
    assert trade["remaining_quantity"] == pytest.approx(0.0)
    assert trade["realized_pnl"] == pytest.approx(60.0)
    events = list_forward_events(user_id, trade["id"])
    assert [e["event_type"] for e in events] == [
        "SIGNAL_IMPORTED", "ENTRY_FILLED", "TP1_FILLED", "TP2_FILLED", "TP3_FILLED"
    ]
    summary = forward_summary(user_id, run["id"])
    assert summary["closed_trades"] == 1
    assert summary["realized_pnl"] == pytest.approx(60.0)
    stopped = stop_forward_run(user_id, run["id"])
    assert stopped["status"] == "stopped"


def test_forward_run_requires_binance_market_data_account(test_user):
    account = v11.create_broker_account(
        test_user["id"], test_user["default_portfolio_id"], "mt5", "MT5 paper"
    )
    with pytest.raises(ValueError, match="Binance paper account"):
        start_forward_run(
            test_user["id"], test_user["default_portfolio_id"],
            account["id"], ["EURUSD"],
        )


def test_forward_run_rejects_cross_tenant_account(test_user):
    user_id = test_user["id"]
    portfolio_id = test_user["default_portfolio_id"]
    other = v11.register_user(
        f"phase7-other-{uuid.uuid4().hex[:10]}@example.com",
        "phase-seven-test-password",
    )
    try:
        other_account = v11.create_broker_account(
            other["id"], other["default_portfolio_id"], "binance", "Other"
        )
        with pytest.raises(LookupError):
            start_forward_run(user_id, portfolio_id, other_account["id"], ["BTCUSDT"])
    finally:
        with session_scope() as db:
            db.execute(delete(User).where(User.id == other["id"]))
