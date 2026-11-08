"""Small, dependency-free resilience primitives for long-running services."""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class ExponentialBackoff:
    base_seconds: float = 1.0
    max_seconds: float = 60.0
    multiplier: float = 2.0
    jitter_fraction: float = 0.2
    attempts: int = 0
    random_fn: Callable[[], float] = random.random

    def __post_init__(self) -> None:
        if self.base_seconds <= 0 or self.max_seconds < self.base_seconds:
            raise ValueError("Backoff requires 0 < base_seconds <= max_seconds")
        if self.multiplier < 1:
            raise ValueError("multiplier must be >= 1")
        if not 0 <= self.jitter_fraction <= 1:
            raise ValueError("jitter_fraction must be between 0 and 1")

    def next_delay(self) -> float:
        raw = min(self.max_seconds, self.base_seconds * (self.multiplier ** self.attempts))
        self.attempts += 1
        # random_fn is injectable to make tests deterministic.
        centered = (self.random_fn() * 2.0) - 1.0
        return max(0.0, raw * (1.0 + centered * self.jitter_fraction))

    def reset(self) -> None:
        self.attempts = 0


class CircuitBreaker:
    """Thread-safe CLOSED/OPEN/HALF_OPEN breaker for optional dependency calls."""

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or reset_timeout_seconds <= 0:
            raise ValueError("Invalid circuit breaker configuration")
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe = False

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if self._clock() - self._opened_at >= self.reset_timeout_seconds:
                return "half_open"
            return "open"

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failures

    def allow_request(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self.reset_timeout_seconds:
                return False
            if self._half_open_probe:
                return False
            self._half_open_probe = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_probe = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._half_open_probe = False
            if self._failures >= self.failure_threshold:
                self._opened_at = self._clock()


def retry_delay(attempt: int, *, base_seconds: float = 0.25,
                max_seconds: float = 5.0) -> float:
    """Deterministic capped exponential delay for bounded in-process retries."""
    if attempt < 0 or base_seconds <= 0 or max_seconds < base_seconds:
        raise ValueError("Invalid retry parameters")
    return min(max_seconds, base_seconds * (2 ** attempt))


def build_operational_health(
    live_price_status: dict,
    live_signal_status: dict,
) -> dict:
    """Combine in-process monitor telemetry without requiring a DB probe."""
    checks = {
        "live_price_monitor": {
            "running": bool(live_price_status.get("running")),
            "connected": bool(live_price_status.get("connected")),
            "last_error": live_price_status.get("last_error"),
        },
        "live_signal_monitor": {
            "running": bool(live_signal_status.get("running")),
            "consecutive_failures": int(live_signal_status.get("consecutive_failures", 0)),
            "last_error": live_signal_status.get("last_error"),
        },
    }
    degraded = any(
        (not item["running"]) or bool(item["last_error"])
        for item in checks.values()
    )
    return {
        "status": "degraded" if degraded else "operational",
        "checks": checks,
        "database_probe_performed": False,
        "execution_allowed": False,
        "note": "In-process service telemetry only; PostgreSQL readiness is reported separately by /health/ready.",
    }
