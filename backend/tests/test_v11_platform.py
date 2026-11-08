from __future__ import annotations

import pytest
import uuid
from fastapi import HTTPException

from app import v11_platform as v11


@pytest.fixture(autouse=True)
def cleanup_test_users(monkeypatch):
    """Keep tests isolated without truncating the shared Neon database."""
    from sqlalchemy import delete
    from app.database import session_scope
    from app.db_models import User

    created_user_ids = []
    original_register = v11.register_user

    def tracked_register(*args, **kwargs):
        result = original_register(*args, **kwargs)
        created_user_ids.append(result["id"])
        return result

    monkeypatch.setattr(v11, "register_user", tracked_register)
    yield

    if created_user_ids:
        with session_scope() as db:
            db.execute(delete(User).where(User.id.in_(created_user_ids)))


def make_user(email=None):
    email = email or f"alice-{uuid.uuid4().hex[:12]}@example.com"
    # Make explicit fixture addresses unique too, so reruns never collide.
    if email in ("alice@example.com", "bob@example.com"):
        local, domain = email.split("@", 1)
        email = f"{local}-{uuid.uuid4().hex[:8]}@{domain}"
    return v11.register_user(email, "correct-horse-battery")


def test_registration_login_and_token_authentication():
    user = make_user()
    session = v11.create_session(user["email"], "correct-horse-battery")
    identity = v11.authenticate_token(session["access_token"])
    assert identity == {"id": user["id"], "email": user["email"]}
    with pytest.raises(HTTPException):
        v11.authenticate_token("invalid-token")


def test_duplicate_email_and_weak_password_are_rejected():
    email = f"duplicate-{uuid.uuid4().hex[:10]}@example.com"
    v11.register_user(email, "correct-horse-battery")

    with pytest.raises(ValueError, match="already exists"):
        v11.register_user(email, "correct-horse-battery")

    weak_email = f"weak-{uuid.uuid4().hex[:10]}@example.com"
    with pytest.raises(ValueError, match="10 characters"):
        v11.register_user(weak_email, "short")

def test_portfolio_and_broker_accounts_are_tenant_scoped():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    alice_portfolio = alice["default_portfolio_id"]
    with pytest.raises(LookupError):
        v11.get_portfolio(bob["id"], alice_portfolio)
    account = v11.create_broker_account(alice["id"], alice_portfolio, "binance", "Binance paper")
    assert account["mode"] == "paper"
    with pytest.raises(LookupError):
        v11.list_broker_accounts(bob["id"], alice_portfolio)


def test_paper_order_open_close_updates_portfolio_equity():
    user = make_user()
    pid = user["default_portfolio_id"]
    account = v11.create_broker_account(user["id"], pid, "mt5", "MT5 paper")
    order = v11.create_paper_order(user["id"], account["id"], "EURUSD", "long", 100, 1.10, 1.09, 1.13)
    assert order["status"] == "open"
    closed = v11.close_paper_order(user["id"], order["id"], 1.12)
    assert closed["status"] == "closed"
    assert closed["realized_pnl"] == pytest.approx(2.0)
    portfolio = v11.get_portfolio(user["id"], pid)
    assert portfolio["cash_equity"] == pytest.approx(10002.0)
    assert portfolio["open_positions"] == 0


def test_portfolio_limits_block_excess_risk_and_capacity():
    user = make_user()
    pid = user["default_portfolio_id"]
    account = v11.create_broker_account(user["id"], pid, "binance", "Binance paper")
    # 1% of 10,000 is 100; this order risks 200.
    with pytest.raises(ValueError, match="Per-trade risk"):
        v11.create_paper_order(user["id"], account["id"], "BTCUSDT", "long", 20, 100, 90, 120)
    # A valid order risks 50, within the 1% per-trade limit.
    v11.create_paper_order(user["id"], account["id"], "BTCUSDT", "long", 5, 100, 90, 120)
    # Portfolio allows 3 open positions; create two more valid positions.
    v11.create_paper_order(user["id"], account["id"], "ETHUSDT", "long", 5, 100, 90, 120)
    v11.create_paper_order(user["id"], account["id"], "SOLUSDT", "long", 5, 100, 90, 120)
    with pytest.raises(ValueError, match="max_open_trades"):
        v11.create_paper_order(user["id"], account["id"], "BNBUSDT", "long", 1, 100, 90, 120)


def test_paper_order_rejects_invalid_price_ordering_and_cross_tenant_close():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    account = v11.create_broker_account(alice["id"], alice["default_portfolio_id"], "binance", "Paper")
    with pytest.raises(ValueError, match="For long orders"):
        v11.create_paper_order(alice["id"], account["id"], "BTCUSDT", "long", 1, 100, 105, 110)
    order = v11.create_paper_order(alice["id"], account["id"], "BTCUSDT", "long", 1, 100, 90, 120)
    with pytest.raises(LookupError):
        v11.close_paper_order(bob["id"], order["id"], 110)


def test_audit_events_are_isolated_per_user():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    assert all(e["event_type"] != "USER_REGISTERED" for e in v11.list_audit_events(bob["id"])) is False
    assert len(v11.list_audit_events(alice["id"])) == 1
    assert len(v11.list_audit_events(bob["id"])) == 1


def test_shared_backtest_history_is_tenant_scoped():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    candles = [
        {"time": 1_800_000_000, "open": 100, "high": 101, "low": 99, "close": 100},
        {"time": 1_800_000_060, "open": 100, "high": 101, "low": 99, "close": 100},
        {"time": 1_800_000_120, "open": 100, "high": 106, "low": 99, "close": 105},
    ]
    result = {"simulation_mode": "shared_portfolio", "trade_count": 0, "net_pnl": 0}
    saved = v11.save_backtest_run(alice["id"], alice["default_portfolio_id"], result)
    history = v11.list_backtest_runs(alice["id"], alice["default_portfolio_id"])
    assert history[0]["id"] == saved["id"]
    assert history[0]["result"]["simulation_mode"] == "shared_portfolio"
    with pytest.raises(LookupError):
        v11.list_backtest_runs(bob["id"], alice["default_portfolio_id"])


def test_http_auth_and_tenant_scoped_paper_workflow():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    suffix = uuid.uuid4().hex[:10]
    app = FastAPI()
    app.include_router(v11.router)
    client = TestClient(app)

    reg = client.post("/api/v1/v11/auth/register", json={
        "email": f"http-user-{suffix}@example.com", "password": "correct-horse-battery"
    })
    assert reg.status_code == 201
    login = client.post("/api/v1/v11/auth/login", json={
        "email": f"http-user-{suffix}@example.com", "password": "correct-horse-battery"
    })
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/v11/auth/me", headers=headers)
    assert me.status_code == 200
    portfolio_id = reg.json()["default_portfolio_id"]
    account = client.post("/api/v1/v11/accounts", headers=headers, json={
        "portfolio_id": portfolio_id, "broker": "binance", "label": "Test paper"
    })
    assert account.status_code == 201
    order = client.post("/api/v1/v11/paper/orders", headers=headers, json={
        "account_id": account.json()["id"], "symbol": "BTCUSDT", "side": "long",
        "quantity": 0.01, "reference_price": 65000, "stop_loss": 64000, "take_profit": 68000
    })
    assert order.status_code == 201
    other_user = client.post("/api/v1/v11/auth/register", json={
        "email": f"another-{suffix}@example.com", "password": "correct-horse-battery"
    }).json()
    other_login = client.post("/api/v1/v11/auth/login", json={
        "email": f"another-{suffix}@example.com", "password": "correct-horse-battery"
    }).json()
    other_headers = {"Authorization": f"Bearer {other_login['access_token']}"}
    cross_tenant = client.get(f"/api/v1/v11/portfolios/{portfolio_id}", headers=other_headers)
    assert cross_tenant.status_code == 404
    logout = client.post("/api/v1/v11/auth/logout", headers=headers)
    assert logout.status_code == 200
    assert client.get("/api/v1/v11/auth/me", headers=headers).status_code == 401
