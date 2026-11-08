from __future__ import annotations

import pytest

from app import historical_signal_engine as engine


def _candles(count: int = 70) -> list[dict]:
    rows = []
    for index in range(count):
        price = 100.0 + index * 0.1
        rows.append({
            "time": index,
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price + 0.2,
            "volume": 10.0,
        })
    return rows


def test_closed_as_of_excludes_candles_not_fully_closed():
    rows = _candles(5)
    result = engine._closed_as_of(rows, "5m", decision_time=303)
    assert [row["time"] for row in result] == [0, 1, 2, 3]


def test_analysis_window_duplicates_last_closed_row():
    rows = _candles(3)
    result = engine._analysis_window(rows)
    assert len(result) == 4
    assert result[-1] == result[-2]


def test_historical_generator_uses_only_closed_prefixes(monkeypatch):
    # Compress intervals for a fast deterministic unit test. Production values
    # remain the real timeframe durations declared by the module.
    monkeypatch.setattr(
        engine, "_INTERVAL_SECONDS",
        {"4h": 1, "1h": 1, "15m": 1, "5m": 1, "1m": 1},
    )
    observed = []

    def fake_smc(symbol, rows, swing_length=3):
        observed.append([row["time"] for row in rows])
        return {
            "structure": "bullish",
            "directional_bias": "bullish",
            "quality_score": 80,
            "events": [],
            "zones": [],
            "last_price": rows[-2]["close"],
        }

    def fake_regime(rows, timeframe):
        return {
            "regime": "trending",
            "volatility_regime": "normal",
            "volume_participation": "normal",
        }

    def fake_scan(*args, **kwargs):
        return {
            "scenarios": [{
                "direction": "bullish",
                "confirmation": "confirmed_trigger",
                "quality_score": 80,
                "zone": {
                    "type": "FVG",
                    "low": 100.0,
                    "high": 101.0,
                    "formed_at": 10,
                },
            }]
        }

    def fake_plan(*args, **kwargs):
        return {
            "rr_filter_passed": True,
            "entry": 100.5,
            "stop_loss": 99.5,
            "take_profits": [
                {"name": "TP1", "price": 101.5, "risk_reward": 1.0},
                {"name": "TP2", "price": 102.5, "risk_reward": 2.0},
            ],
        }

    monkeypatch.setattr(engine, "analyze_smc", fake_smc)
    monkeypatch.setattr(engine, "analyze_market_regime", fake_regime)
    monkeypatch.setattr(engine, "scan_symbol", fake_scan)
    monkeypatch.setattr(engine, "_make_plan", fake_plan)

    data = {tf: _candles() for tf in engine.TIMEFRAMES}
    result = engine.generate_historical_smc_signals(
        "BTCUSDT", data, min_quality_score=65, min_rr=2.0
    )

    assert result["status"] == "completed"
    assert result["signal_count"] == 1
    signal = result["signals"][0]
    assert signal["index"] == 49
    assert signal["signal_time"] == 50
    assert signal["execution_allowed"] is False

    # At decision time 50, only candles with open time <= 49 are closed.
    assert observed
    assert all(times[-1] == times[-2] for times in observed)
    # Five analyzer calls are made per decision point (one per timeframe).
    for offset in range(0, len(observed), len(engine.TIMEFRAMES)):
        batch = observed[offset:offset + len(engine.TIMEFRAMES)]
        if len(batch) == len(engine.TIMEFRAMES):
            expected_last_closed = 49 + offset // len(engine.TIMEFRAMES)
            assert all(max(times[:-1]) == expected_last_closed for times in batch)


def test_historical_generator_rejects_non_chronological_data():
    data = {tf: _candles() for tf in engine.TIMEFRAMES}
    data["5m"][5], data["5m"][6] = data["5m"][6], data["5m"][5]
    with pytest.raises(ValueError, match="strictly increasing"):
        engine.generate_historical_smc_signals("BTCUSDT", data)
