from __future__ import annotations

import asyncio

import pytest

from app.operational_resilience import (
    CircuitBreaker,
    ExponentialBackoff,
    build_operational_health,
    retry_delay,
)
from app.live_signal_monitor import LiveSignalMonitor


def test_exponential_backoff_grows_caps_and_resets():
    backoff = ExponentialBackoff(
        base_seconds=2, max_seconds=5, multiplier=2,
        jitter_fraction=0, random_fn=lambda: 0.5,
    )
    assert [backoff.next_delay() for _ in range(4)] == [2, 4, 5, 5]
    assert backoff.attempts == 4
    backoff.reset()
    assert backoff.next_delay() == 2


def test_exponential_backoff_applies_bounded_jitter():
    backoff = ExponentialBackoff(
        base_seconds=10, max_seconds=20, jitter_fraction=0.2,
        random_fn=lambda: 1.0,
    )
    assert backoff.next_delay() == 12


def test_exponential_backoff_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        ExponentialBackoff(base_seconds=0)


def test_circuit_breaker_opens_and_allows_single_half_open_probe():
    now = [100.0]
    breaker = CircuitBreaker(
        failure_threshold=2, reset_timeout_seconds=10,
        clock=lambda: now[0],
    )
    assert breaker.allow_request()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == "open"
    assert not breaker.allow_request()
    now[0] += 10
    assert breaker.state == "half_open"
    assert breaker.allow_request()
    assert not breaker.allow_request()
    breaker.record_success()
    assert breaker.state == "closed"
    assert breaker.allow_request()


def test_circuit_breaker_reopens_after_failed_half_open_probe():
    now = [0.0]
    breaker = CircuitBreaker(1, 5, clock=lambda: now[0])
    breaker.record_failure()
    now[0] = 5
    assert breaker.allow_request()
    breaker.record_failure()
    assert breaker.state == "open"


def test_retry_delay_is_capped_and_validated():
    assert [retry_delay(i, base_seconds=0.5, max_seconds=2) for i in range(4)] == [
        0.5, 1.0, 2.0, 2.0
    ]
    with pytest.raises(ValueError):
        retry_delay(-1)


def test_operational_health_is_read_only_and_flags_stopped_service():
    result = build_operational_health(
        {"running": True, "connected": False, "last_error": None},
        {"running": False, "last_error": "worker stopped"},
    )
    assert result["status"] == "degraded"
    assert result["database_probe_performed"] is False
    assert result["execution_allowed"] is False


@pytest.mark.asyncio
async def test_live_signal_monitor_retries_transient_evaluation_failure():
    calls = []

    async def evaluate(symbol, fetcher, **kwargs):
        calls.append(symbol)
        if len(calls) == 1:
            raise RuntimeError("temporary provider failure")
        return {"decision_time": 1_800_000_000, "signals": []}

    monitor = LiveSignalMonitor(
        evaluate_fn=evaluate,
        persist_fn=lambda plan: {},
        symbols_fn=lambda: ["BTCUSDT"],
        retry_base_seconds=0.001,
    )
    result = await monitor.run_once()
    assert result["status"] == "completed"
    assert result["symbols_checked"] == 1
    assert calls == ["BTCUSDT", "BTCUSDT"]
    status = monitor.status()
    assert status["evaluation_retries"] == 1
    assert status["consecutive_failures"] == 0
    assert status["last_successful_cycle_at"] is not None


@pytest.mark.asyncio
async def test_live_signal_monitor_exposes_failed_cycle_metrics():
    async def evaluate(symbol, fetcher, **kwargs):
        raise RuntimeError("provider offline")

    monitor = LiveSignalMonitor(
        evaluate_fn=evaluate,
        persist_fn=lambda plan: {},
        symbols_fn=lambda: ["BTCUSDT"],
        evaluation_retry_attempts=1,
    )
    result = await monitor.run_once()
    assert result["results"][0]["status"] == "failed"
    status = monitor.status()
    assert status["consecutive_failures"] == 1
    assert status["cycle_duration_ms"] is not None
    assert "provider offline" in status["last_error"]
