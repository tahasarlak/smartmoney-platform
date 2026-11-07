import pytest
from app.risk_controls import evaluate_risk


BASE = dict(
    balance=10000, equity=10000, day_start_equity=10000,
    week_start_equity=10000, month_start_equity=10000, peak_equity=10000,
    entry=100, stop=98, quantity=10,
    settings={
        "risk_basis": "equity", "risk_per_trade_pct": 0.5,
        "max_daily_loss_pct": 3, "max_weekly_loss_pct": 6,
        "max_monthly_loss_pct": 10, "max_drawdown_pct": 15,
        "max_open_trades": 3, "max_total_open_risk_pct": 3,
        "allow_counter_trend": True,
    },
)


def test_risk_preflight_accepts_within_limits():
    result = evaluate_risk(**BASE)
    assert result["allowed"] is True
    assert result["risk_cash"] == 20
    assert result["execution_allowed"] is False


def test_risk_preflight_blocks_daily_loss_and_countertrend():
    args = {**BASE, "equity": 9600, "counter_trend": True}
    args["settings"] = {**BASE["settings"], "allow_counter_trend": False}
    result = evaluate_risk(**args)
    assert result["allowed"] is False
    assert any("daily loss" in x for x in result["blockers"])
    assert any("counter-trend" in x for x in result["blockers"])


def test_risk_preflight_rejects_zero_account_values():
    with pytest.raises(ValueError):
        evaluate_risk(**{**BASE, "balance": 0})
