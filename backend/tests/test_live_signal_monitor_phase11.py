from __future__ import annotations

import asyncio
import inspect

import pytest

from app.live_signal_monitor import (
    LiveSignalMonitor,
    live_signal_idempotency_key,
)


def _plan():
    return {
        "symbol": "BTCUSDT",
        "signal_time": 1_800_000_000,
        "direction": "bullish",
        "setup_class": "BOS_FVG",
        "status": "pending_retest",
        "execution_allowed": False,
    }


def test_idempotency_key_is_stable_and_fits_signal_source_column():
    first = live_signal_idempotency_key(_plan())
    second = live_signal_idempotency_key(_plan())
    assert first == second
    assert first.startswith("live_smc_")
    assert len(first) <= 40


def test_idempotency_key_changes_for_new_decision_candle():
    first = live_signal_idempotency_key(_plan())
    changed = _plan()
    changed["signal_time"] += 300
    assert live_signal_idempotency_key(changed) != first


def test_idempotency_key_rejects_invalid_signal_identity():
    invalid = _plan()
    invalid["signal_time"] = 0
    with pytest.raises(ValueError, match="positive signal_time"):
        live_signal_idempotency_key(invalid)


@pytest.mark.asyncio
async def test_run_once_persists_new_signals_and_reports_counts():
    async def fake_evaluate(symbol, fetcher, **kwargs):
        assert symbol == "BTCUSDT"
        assert kwargs["use_regime_filter"] is True
        return {"decision_time": 1_800_000_000, "signals": [_plan()]}

    saved = []

    def fake_persist(plan):
        saved.append(plan)
        return {"id": "signal-1", "deduplicated": False}

    monitor = LiveSignalMonitor(
        evaluate_fn=fake_evaluate,
        persist_fn=fake_persist,
        symbols_fn=lambda: ["BTCUSDT", "btcusdt"],
    )
    result = await monitor.run_once()
    assert result["status"] == "completed"
    assert result["symbols_checked"] == 1
    assert result["signals_created"] == 1
    assert result["signals_deduplicated"] == 0
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_run_once_counts_deduplicated_signals():
    async def fake_evaluate(symbol, fetcher, **kwargs):
        return {"decision_time": 1_800_000_000, "signals": [_plan()]}

    monitor = LiveSignalMonitor(
        evaluate_fn=fake_evaluate,
        persist_fn=lambda plan: {"id": "existing", "deduplicated": True},
        symbols_fn=lambda: ["BTCUSDT"],
    )
    result = await monitor.run_once()
    assert result["signals_created"] == 0
    assert result["signals_deduplicated"] == 1


@pytest.mark.asyncio
async def test_run_once_isolates_symbol_failures_and_continues():
    async def fake_evaluate(symbol, fetcher, **kwargs):
        if symbol == "BADUSDT":
            raise RuntimeError("provider unavailable")
        return {"decision_time": 1_800_000_000, "signals": []}

    monitor = LiveSignalMonitor(
        evaluate_fn=fake_evaluate,
        persist_fn=lambda plan: {},
        symbols_fn=lambda: ["BADUSDT", "BTCUSDT"],
    )
    result = await monitor.run_once()
    assert result["symbols_checked"] == 2
    assert result["results"][0]["status"] == "failed"
    assert result["results"][1]["status"] == "completed"


def test_signal_journal_supports_atomic_idempotent_live_source():
    from app.signal_journal import create_signal
    params = inspect.signature(create_signal).parameters
    assert "source" in params
    assert "idempotency_key" in params


def test_monitor_interval_is_fixed_to_five_minutes():
    with pytest.raises(ValueError, match="fixed at 300"):
        LiveSignalMonitor(interval_seconds=60)
