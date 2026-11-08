import math
import pytest

from app.performance_analytics import build_portfolio_performance


def trade(id, pnl, *, symbol="BTCUSDT", side="long", status="closed", entry=100, stop=95, qty=1, t=1):
    return {
        "id": id, "symbol": symbol, "side": side, "status": status,
        "planned_entry": entry, "initial_stop_loss": stop, "quantity": qty,
        "net_realized_pnl": pnl, "realized_pnl": pnl, "fees_paid": 0,
        "closed_at_ms": t * 1000, "last_event_time_ms": t * 1000,
    }


def test_closed_trade_metrics_and_equity_curve():
    result = build_portfolio_performance(
        initial_equity=1000,
        trades=[trade("1", 10, t=1), trade("2", -5, t=2), trade("3", 15, t=3)],
    )
    assert result["closed_trade_count"] == 3
    assert result["realized_net_pnl_to_date"] == 20
    assert result["cash_equity_to_date"] == 1020
    assert result["win_rate_pct"] == pytest.approx(66.6667)
    assert result["max_drawdown_cash"] == 5
    assert result["max_drawdown_pct"] == pytest.approx(0.49505)
    assert len(result["equity_curve"]) == 4


def test_partial_realized_pnl_affects_cash_but_not_closed_sample():
    result = build_portfolio_performance(
        initial_equity=500,
        trades=[trade("1", 12, status="open"), trade("2", 8, status="closed", t=2)],
    )
    assert result["realized_net_pnl_to_date"] == 20
    assert result["cash_equity_to_date"] == 520
    assert result["closed_trade_count"] == 1
    assert result["equity_curve"][-1]["equity"] == 508


def test_cohort_ranking_groups_by_symbol_and_direction():
    result = build_portfolio_performance(
        initial_equity=1000,
        trades=[
            trade("1", 20, symbol="BTCUSDT", side="long", t=1),
            trade("2", -4, symbol="ETHUSDT", side="short", t=2),
        ],
    )
    assert {x["group"] for x in result["cohort_ranking"]} == {"BTCUSDT · LONG", "ETHUSDT · SHORT"}


def test_ratios_are_not_annualized_and_sample_warning_is_present():
    result = build_portfolio_performance(
        initial_equity=1000,
        trades=[trade("1", 10, t=1), trade("2", -5, t=2), trade("3", 15, t=3)],
    )
    assert result["sharpe_per_trade"] is not None
    assert result["sortino_per_trade"] is not None
    assert result["sample_quality"] == "insufficient"
    assert "non_annualized" in result["methodology"]["sharpe_sortino"]


def test_invalid_equity_rejected():
    with pytest.raises(ValueError):
        build_portfolio_performance(initial_equity=0, trades=[])
