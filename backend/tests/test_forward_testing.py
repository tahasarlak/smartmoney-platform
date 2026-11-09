from __future__ import annotations

import pytest

from app.forward_testing import (
    adverse_fill, entry_triggered, exit_triggered, normalize_symbols,
)


def test_normalize_symbols_deduplicates_and_uppercases():
    assert normalize_symbols(["btcusdt", "ETHUSDT", "BTCUSDT"]) == ["BTCUSDT", "ETHUSDT"]


def test_normalize_symbols_rejects_invalid_and_too_many():
    with pytest.raises(ValueError):
        normalize_symbols(["BTC/USDT"])
    with pytest.raises(ValueError):
        normalize_symbols([f"COIN{i}" for i in range(51)])


def test_entry_triggers_for_long_and_short_without_lookahead():
    assert entry_triggered("long", 99.9, 100)
    assert not entry_triggered("long", 100.1, 100)
    assert entry_triggered("short", 100.1, 100)
    assert not entry_triggered("short", 99.9, 100)


def test_adverse_slippage_is_applied_in_the_wrong_direction_for_trader():
    assert adverse_fill(100, "long", True, 10) == pytest.approx(100.1)
    assert adverse_fill(100, "long", False, 10) == pytest.approx(99.9)
    assert adverse_fill(100, "short", True, 10) == pytest.approx(99.9)
    assert adverse_fill(100, "short", False, 10) == pytest.approx(100.1)


def test_exit_trigger_detects_stop_and_target_for_both_directions():
    assert exit_triggered("long", 94, 95, 105) == (True, False)
    assert exit_triggered("long", 106, 95, 105) == (False, True)
    assert exit_triggered("short", 106, 105, 95) == (True, False)
    assert exit_triggered("short", 94, 105, 95) == (False, True)


def test_invalid_fill_inputs_are_rejected():
    with pytest.raises(ValueError):
        adverse_fill(0, "long", True, 2)
    with pytest.raises(ValueError):
        adverse_fill(100, "unknown", True, 2)


def test_forward_testing_api_routes_are_registered():
    from app.main import app

    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/v11/forward/runs" in paths
    assert "/api/v1/v11/forward/runs/{run_id}/stop" in paths
    assert "/api/v1/v11/forward/runs/{run_id}/summary" in paths
    assert "/api/v1/v11/forward/runs/{run_id}/comparison" in paths
    assert "/api/v1/v11/forward/trades/{trade_id}/events" in paths

