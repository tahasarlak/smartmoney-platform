import pytest
from app.strategy_validation import build_strategy_validation


def trade(i, pnl, *, status="closed", entry=100, stop=95, qty=1):
    return {
        "id": str(i), "status": status, "symbol": "BTCUSDT", "side": "long",
        "planned_entry": entry, "initial_stop_loss": stop, "quantity": qty,
        "net_realized_pnl": pnl, "realized_pnl": pnl, "fees_paid": 0,
    }


def test_bootstrap_validation_is_reproducible_and_uses_r_multiple():
    trades = [trade(i, 10 if i % 3 else -5) for i in range(1, 41)]
    first = build_strategy_validation(trades=trades, bootstrap_iterations=500)
    second = build_strategy_validation(trades=trades, bootstrap_iterations=500)
    assert first == second
    assert first["closed_trade_count"] == 40
    assert first["sample_quality"] == "preliminary"
    assert first["expectancy_r_ci95"] is not None
    assert first["execution_allowed"] is False


def test_open_trades_are_excluded_from_validation_sample():
    result = build_strategy_validation(trades=[trade(1, 5), trade(2, 100, status="open")])
    assert result["closed_trade_count"] == 1
    assert result["bootstrap_iterations"] == 0
    assert result["expectancy_r_ci95"] is None


def test_invalid_initial_risk_is_excluded():
    result = build_strategy_validation(trades=[trade(1, 5, entry=100, stop=100)])
    assert result["closed_trade_count"] == 0
    assert result["status"] == "insufficient_sample"


def test_losing_streak_and_win_rate_interval():
    values = [10, -5, -5, -5, 10, -5]
    result = build_strategy_validation(trades=[trade(i, p) for i, p in enumerate(values)])
    assert result["longest_losing_streak"] == 3
    assert result["win_rate_ci95_pct"] is not None


def test_invalid_bootstrap_count_rejected():
    with pytest.raises(ValueError):
        build_strategy_validation(trades=[], bootstrap_iterations=100)
