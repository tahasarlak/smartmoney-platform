from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    risk_cash: float
    risk_pct_of_account: float
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "risk_cash": round(self.risk_cash, 2),
            "risk_pct_of_account": round(self.risk_pct_of_account, 4),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "execution_allowed": False,
        }


def evaluate_risk(
    *,
    balance: float,
    equity: float,
    day_start_equity: float,
    week_start_equity: float,
    month_start_equity: float,
    peak_equity: float,
    entry: float,
    stop: float,
    quantity: float,
    settings: dict[str, Any],
    open_trades: list[dict[str, Any]] | None = None,
    counter_trend: bool = False,
    correlation_group: str | None = None,
) -> dict[str, Any]:
    """Server-side preflight only. It never submits an order."""
    values = {
        "balance": balance, "equity": equity, "day_start_equity": day_start_equity,
        "week_start_equity": week_start_equity, "month_start_equity": month_start_equity,
        "peak_equity": peak_equity, "entry": entry, "stop": stop, "quantity": quantity,
    }
    if any(float(v) <= 0 for v in values.values()):
        raise ValueError("Account, price and quantity values must be positive")

    basis_name = settings.get("risk_basis", "equity")
    if basis_name not in ("balance", "equity"):
        raise ValueError("risk_basis must be balance or equity")
    basis = float(balance if basis_name == "balance" else equity)
    risk_pct = float(settings.get("risk_per_trade_pct", 0.5))
    if not 0 < risk_pct <= 2:
        raise ValueError("risk_per_trade_pct must be greater than 0 and at most 2")

    risk_cash = abs(float(entry) - float(stop)) * float(quantity)
    risk_pct_actual = risk_cash / basis * 100
    blockers: list[str] = []
    warnings: list[str] = []

    def loss_pct(start: float, current: float) -> float:
        return max(0.0, (start - current) / start * 100.0)

    daily = loss_pct(day_start_equity, equity)
    weekly = loss_pct(week_start_equity, equity)
    monthly = loss_pct(month_start_equity, equity)
    drawdown = loss_pct(peak_equity, equity)

    limits = [
        ("daily loss", daily, float(settings.get("max_daily_loss_pct", 3))),
        ("weekly loss", weekly, float(settings.get("max_weekly_loss_pct", 6))),
        ("monthly loss", monthly, float(settings.get("max_monthly_loss_pct", 10))),
        ("drawdown", drawdown, float(settings.get("max_drawdown_pct", 15))),
    ]
    for label, observed, limit in limits:
        if observed >= limit:
            blockers.append(f"{label} limit reached ({observed:.2f}% >= {limit:.2f}%)")

    if counter_trend and not bool(settings.get("allow_counter_trend", True)):
        blockers.append("counter-trend trading is disabled")

    trades = open_trades or []
    max_open = int(settings.get("max_open_trades", 3))
    if len(trades) >= max_open:
        blockers.append(f"maximum open trades reached ({len(trades)} >= {max_open})")

    max_aggregate_pct = float(settings.get("max_total_open_risk_pct", 3))
    existing_risk = sum(max(0.0, float(x.get("risk_cash", 0))) for x in trades)
    aggregate_pct = (existing_risk + risk_cash) / basis * 100
    if aggregate_pct > max_aggregate_pct:
        blockers.append(
            f"aggregate open risk would exceed limit ({aggregate_pct:.2f}% > {max_aggregate_pct:.2f}%)"
        )

    if correlation_group:
        correlated = [x for x in trades if x.get("correlation_group") == correlation_group]
        if correlated:
            warnings.append(
                f"{len(correlated)} existing open trade(s) share correlation group {correlation_group}"
            )

    if risk_pct_actual > risk_pct + 1e-9:
        blockers.append(
            f"position risk exceeds configured per-trade risk ({risk_pct_actual:.2f}% > {risk_pct:.2f}%)"
        )

    decision = RiskDecision(
        allowed=not blockers,
        risk_cash=risk_cash,
        risk_pct_of_account=risk_pct_actual,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    ).as_dict()
    decision.update({
        "account_basis": basis_name,
        "account_value": round(basis, 2),
        "daily_loss_pct": round(daily, 4),
        "weekly_loss_pct": round(weekly, 4),
        "monthly_loss_pct": round(monthly, 4),
        "drawdown_pct": round(drawdown, 4),
        "aggregate_open_risk_pct": round(aggregate_pct, 4),
        "correlation_group": correlation_group,
    })
    return decision
