from __future__ import annotations

import copy

import pytest

from app import lookahead_audit
from app.historical_signal_engine import _closed_as_of


def _series(tf, duration, count=60):
    rows = []
    for i in range(count):
        base = 100.0 + i
        rows.append({
            "time": 1_700_000_000 + i * duration,
            "open": base,
            "high": base + 2,
            "low": base - 2,
            "close": base + 1,
        })
    return rows


def _dataset():
    return {
        "4h": _series("4h", 14_400),
        "1h": _series("1h", 3_600),
        "15m": _series("15m", 900),
        "5m": _series("5m", 300),
        "1m": _series("1m", 60),
    }


@pytest.mark.parametrize(
    "tf,duration",
    [("4h", 14_400), ("1h", 3_600), ("15m", 900), ("5m", 300), ("1m", 60)],
)
def test_only_fully_closed_candles_are_visible(tf, duration):
    rows = _series(tf, duration, 3)
    decision = rows[1]["time"] + duration
    visible = _closed_as_of(rows, tf, decision)
    assert visible == rows[:2]
    assert all(row["time"] + duration <= decision for row in visible)


def test_audit_rejects_changes_inside_information_cutoff():
    original = _dataset()
    variant = copy.deepcopy(original)
    variant["5m"][0]["close"] += 0.25

    with pytest.raises(ValueError, match="differ in information available"):
        lookahead_audit.audit_future_invariance(
            "BTCUSDT", original, variant, cutoff_time=original["5m"][10]["time"] + 300
        )


def test_future_only_perturbation_keeps_pre_cutoff_signals_identical(monkeypatch):
    original = _dataset()
    variant = copy.deepcopy(original)
    cutoff = original["5m"][54]["time"] + 300

    # Change only bars that close after the cutoff; preserve valid OHLC geometry.
    for timeframe, duration in (("4h", 14_400), ("1h", 3_600), ("15m", 900), ("5m", 300), ("1m", 60)):
        for row in variant[timeframe]:
            if row["time"] + duration > cutoff:
                row["open"] += 5
                row["high"] += 5
                row["low"] += 5
                row["close"] += 5

    calls = {"count": 0}

    def fake_smc(symbol, rows, swing_length=3):
        return {"trend": "neutral"}

    def fake_regime(rows, timeframe):
        return {"regime": "range"}

    def fake_scan(symbol, windows, analyses, settings, regimes):
        # Output depends only on data passed to this call; no external/future state.
        return {"scenarios": []}

    # Patch the imported generator's dependencies so both runs are deterministic
    # and the engine still performs its real closed-candle slicing.
    from app import historical_signal_engine as engine
    monkeypatch.setattr(engine, "analyze_smc", fake_smc)
    monkeypatch.setattr(engine, "analyze_market_regime", fake_regime)
    monkeypatch.setattr(engine, "scan_symbol", fake_scan)

    result = lookahead_audit.audit_future_invariance(
        "BTCUSDT", original, variant, cutoff_time=cutoff,
        generator_kwargs={},
    )
    assert result["status"] == "passed"
    assert result["signals_identical"] is True
    assert result["execution_allowed"] is False
