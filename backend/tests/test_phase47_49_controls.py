import pytest

from app.production_controls import evaluate_testnet_order_limits, worker_liveness


def test_testnet_order_limit_allows_small_order_within_limits(monkeypatch):
    monkeypatch.setenv("TRADF_TESTNET_MAX_ORDER_NOTIONAL_USDT", "50")
    monkeypatch.setenv("TRADF_TESTNET_MAX_OPEN_ORDERS", "3")
    monkeypatch.setenv("TRADF_TESTNET_MAX_PORTFOLIO_EXPOSURE_PCT", "10")
    result = evaluate_testnet_order_limits(
        quantity="0.001", price="10000", active_order_notionals=[],
        portfolio_equity=1000,
    )
    assert result["allowed"] is True
    assert result["requested_notional"] == 10
    assert result["execution_allowed"] is False


def test_testnet_order_limit_rejects_single_order_cap(monkeypatch):
    monkeypatch.setenv("TRADF_TESTNET_MAX_ORDER_NOTIONAL_USDT", "25")
    result = evaluate_testnet_order_limits(
        quantity="0.01", price="5000", active_order_notionals=[],
        portfolio_equity=10000,
    )
    assert result["allowed"] is False
    assert "single_order_notional_limit_exceeded" in result["reasons"]


def test_testnet_order_limit_rejects_too_many_open_orders(monkeypatch):
    monkeypatch.setenv("TRADF_TESTNET_MAX_OPEN_ORDERS", "2")
    result = evaluate_testnet_order_limits(
        quantity="0.001", price="1000",
        active_order_notionals=["1", "2"], portfolio_equity=10000,
    )
    assert "maximum_open_orders_reached" in result["reasons"]


def test_testnet_order_limit_rejects_aggregate_exposure(monkeypatch):
    monkeypatch.setenv("TRADF_TESTNET_MAX_PORTFOLIO_EXPOSURE_PCT", "5")
    result = evaluate_testnet_order_limits(
        quantity="0.01", price="1000",
        active_order_notionals=["495"], portfolio_equity=10000,
    )
    assert "portfolio_gross_exposure_limit_exceeded" in result["reasons"]


@pytest.mark.parametrize("quantity,price", [("NaN", "10"), ("Infinity", "10"), ("0", "10"), ("1", "-1")])
def test_testnet_order_limit_rejects_invalid_decimals(quantity, price):
    with pytest.raises(ValueError):
        evaluate_testnet_order_limits(
            quantity=quantity, price=price, active_order_notionals=[],
            portfolio_equity=1000,
        )


def test_worker_heartbeat_fresh_is_healthy_but_not_execution_authorization():
    result = worker_liveness(heartbeat_age_seconds=5, worker_status="running", stale_after_seconds=30)
    assert result["status"] == "healthy"
    assert result["worker_running"] is True
    assert result["execution_allowed"] is False


def test_worker_heartbeat_stale_or_stopped_is_not_healthy():
    assert worker_liveness(heartbeat_age_seconds=60, worker_status="running")["worker_running"] is False
    assert worker_liveness(heartbeat_age_seconds=1, worker_status="stopped")["worker_running"] is False


def test_reconciliation_route_exists_and_is_post_only():
    from app.production_infrastructure import router
    route = next(r for r in router.routes if r.path.endswith("/exchange/testnet/orders/reconcile"))
    assert route.methods == {"POST"}


def test_worker_status_route_exists_and_is_read_only():
    from app.production_infrastructure import router
    route = next(r for r in router.routes if r.path.endswith("/worker/status"))
    assert route.methods == {"GET"}
