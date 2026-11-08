from __future__ import annotations

from typing import Any

from .forward_testing import (
    forward_summary,
    list_forward_runs,
    list_forward_trades,
    start_forward_run,
    stop_forward_run,
)
from .market_store import list_watchlist


def start_paper_automation(
    user_id: str,
    *,
    portfolio_id: str,
    account_id: str,
    symbols: list[str] | None = None,
    use_watchlist: bool = True,
    risk_per_trade_pct: float = 0.25,
    min_quality_score: int = 70,
    commission_pct: float = 0.04,
    slippage_bps: float = 2.0,
    confirm_paper_only: bool = False,
) -> dict[str, Any]:
    """Explicitly opt a tenant portfolio into existing tick-driven forward paper testing.

    Reuses ForwardTestRun and the Binance live-price monitor. It does not create
    broker orders, touch exchange credentials, or enable live execution.
    """
    if confirm_paper_only is not True:
        raise ValueError("Explicit confirm_paper_only=true is required")
    if use_watchlist:
        selected = list_watchlist()
        if symbols:
            requested = {str(item).strip().upper() for item in symbols if str(item).strip()}
            selected = [item for item in selected if item.upper() in requested]
    else:
        selected = symbols or []
    normalized = sorted({str(item).strip().upper() for item in selected if str(item).strip()})
    if not normalized:
        raise ValueError("No symbols selected; add symbols to the market watchlist or provide symbols")
    if len(normalized) > 50:
        raise ValueError("A paper automation run supports at most 50 symbols")

    run = start_forward_run(
        user_id=user_id,
        portfolio_id=portfolio_id,
        account_id=account_id,
        symbols=normalized,
        risk_per_trade_pct=risk_per_trade_pct,
        min_quality_score=min_quality_score,
        commission_pct=commission_pct,
        slippage_bps=slippage_bps,
        include_existing_signals=False,
    )
    return {
        **run,
        "automation": "enabled",
        "mode": "paper",
        "signal_source": "postgresql_signal_journal",
        "market_data_source": "binance_public_websocket",
        "include_existing_signals": False,
        "live_execution_enabled": False,
        "execution_allowed": False,
        "note": "Only signals created after this run starts can be imported. No exchange orders are submitted.",
    }


def paper_automation_status(user_id: str, portfolio_id: str) -> dict[str, Any]:
    runs = list_forward_runs(user_id, portfolio_id, limit=20)
    active = [item for item in runs if item.get("status") in ("active", "stopping")]
    selected = active[0] if active else (runs[0] if runs else None)
    if selected is None:
        return {
            "status": "not_configured",
            "active": False,
            "portfolio_id": portfolio_id,
            "runs": [],
            "mode": "paper",
            "live_execution_enabled": False,
            "execution_allowed": False,
        }
    run_id = selected["id"]
    summary = forward_summary(user_id, run_id)
    trades = list_forward_trades(user_id, run_id, limit=100)
    return {
        "status": selected["status"],
        "active": selected["status"] in ("active", "stopping"),
        "run": selected,
        "summary": summary,
        "recent_trades": trades,
        "runs": runs,
        "mode": "paper",
        "live_execution_enabled": False,
        "execution_allowed": False,
    }


def stop_paper_automation(user_id: str, run_id: str) -> dict[str, Any]:
    run = stop_forward_run(user_id, run_id)
    return {
        **run,
        "automation": "stopping" if run.get("status") == "stopping" else "stopped",
        "mode": "paper",
        "live_execution_enabled": False,
        "execution_allowed": False,
        "note": "Stopping prevents new signal imports; existing paper positions are allowed to reach terminal states.",
    }
