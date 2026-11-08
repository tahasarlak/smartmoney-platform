from __future__ import annotations

import pytest

import app.paper_automation as service
from app.paper_automation_router import PaperAutomationStartRequest


def test_start_requires_explicit_paper_confirmation():
    with pytest.raises(ValueError, match="confirm_paper_only"):
        service.start_paper_automation(
            "user-1", portfolio_id="p-1", account_id="a-1",
            symbols=["BTCUSDT"], use_watchlist=False,
        )


def test_start_uses_watchlist_and_never_imports_old_signals(monkeypatch):
    captured = {}
    monkeypatch.setattr(service, "list_watchlist", lambda: ["btcusdt", "ETHUSDT"])

    def fake_start(**kwargs):
        captured.update(kwargs)
        return {"id": "run-1", "status": "active", "symbols": kwargs["symbols"]}

    monkeypatch.setattr(service, "start_forward_run", fake_start)
    result = service.start_paper_automation(
        "user-1", portfolio_id="p-1", account_id="a-1",
        use_watchlist=True, risk_per_trade_pct=0.25,
        confirm_paper_only=True,
    )
    assert captured["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert captured["include_existing_signals"] is False
    assert result["mode"] == "paper"
    assert result["execution_allowed"] is False


def test_start_can_filter_watchlist(monkeypatch):
    captured = {}
    monkeypatch.setattr(service, "list_watchlist", lambda: ["BTCUSDT", "ETHUSDT"])
    monkeypatch.setattr(service, "start_forward_run", lambda **kwargs: captured.update(kwargs) or {"id": "r"})
    service.start_paper_automation(
        "u", portfolio_id="p", account_id="a", symbols=["ethusdt"],
        use_watchlist=True, confirm_paper_only=True,
    )
    assert captured["symbols"] == ["ETHUSDT"]


def test_start_rejects_empty_watchlist(monkeypatch):
    monkeypatch.setattr(service, "list_watchlist", lambda: [])
    with pytest.raises(ValueError, match="No symbols selected"):
        service.start_paper_automation(
            "u", portfolio_id="p", account_id="a", use_watchlist=True,
            confirm_paper_only=True,
        )


def test_start_rejects_more_than_50_symbols(monkeypatch):
    monkeypatch.setattr(service, "start_forward_run", lambda **kwargs: kwargs)
    with pytest.raises(ValueError, match="at most 50"):
        service.start_paper_automation(
            "u", portfolio_id="p", account_id="a",
            symbols=[f"T{i}USDT" for i in range(51)], use_watchlist=False,
            confirm_paper_only=True,
        )


def test_status_returns_not_configured_when_no_runs(monkeypatch):
    monkeypatch.setattr(service, "list_forward_runs", lambda *args, **kwargs: [])
    result = service.paper_automation_status("u", "p")
    assert result["status"] == "not_configured"
    assert result["active"] is False
    assert result["execution_allowed"] is False


def test_status_returns_active_run_and_summary(monkeypatch):
    monkeypatch.setattr(service, "list_forward_runs", lambda *args, **kwargs: [
        {"id": "r1", "status": "active"}
    ])
    monkeypatch.setattr(service, "forward_summary", lambda *args: {"trade_count": 2})
    monkeypatch.setattr(service, "list_forward_trades", lambda *args, **kwargs: [{"id": "t1"}])
    result = service.paper_automation_status("u", "p")
    assert result["active"] is True
    assert result["summary"]["trade_count"] == 2
    assert len(result["recent_trades"]) == 1


def test_stop_marks_automation_as_stopped(monkeypatch):
    monkeypatch.setattr(service, "stop_forward_run", lambda *args: {"id": "r1", "status": "stopped"})
    result = service.stop_paper_automation("u", "r1")
    assert result["automation"] == "stopped"
    assert result["execution_allowed"] is False


def test_request_requires_explicit_confirmation_and_symbols_when_not_using_watchlist():
    with pytest.raises(Exception):
        PaperAutomationStartRequest(
            portfolio_id="p", account_id="a", use_watchlist=False,
            symbols=["BTCUSDT"], confirm_paper_only=False,
        )
    payload = PaperAutomationStartRequest(
        portfolio_id="p", account_id="a", use_watchlist=False,
        symbols=["BTCUSDT"], confirm_paper_only=True,
    )
    assert payload.confirm_paper_only is True
