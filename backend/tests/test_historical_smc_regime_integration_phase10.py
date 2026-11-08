from __future__ import annotations

from app import historical_signal_engine as engine


def _rows(tf, count=70, end_time=1_700_000_000):
    duration = {"4h": 14_400, "1h": 3_600, "15m": 900, "5m": 300, "1m": 60}[tf]
    start_time = end_time - count * duration
    rows = []
    for i in range(count):
        price = 100 + i * 0.2
        rows.append({
            "time": start_time + i * duration,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price + 0.2,
            "volume": 100,
        })
    return rows


def _data():
    five_minute_start = 1_700_000_000
    return {
        "4h": _rows("4h", end_time=five_minute_start),
        "1h": _rows("1h", end_time=five_minute_start),
        "15m": _rows("15m", end_time=five_minute_start),
        "5m": _rows("5m", end_time=five_minute_start + 70 * 300),
        "1m": _rows("1m", end_time=five_minute_start),
    }


def _scenario(direction="bullish"):
    return {
        "confirmation": "confirmed_trigger",
        "quality_score": 90,
        "direction": direction,
        "zone": {"formed_at": "zone-1", "type": "fvg", "low": 100, "high": 101},
    }


def _patch_engine(monkeypatch, regime):
    monkeypatch.setattr(engine, "analyze_smc", lambda *a, **k: {"trend": "neutral"})
    monkeypatch.setattr(engine, "analyze_market_regime", lambda *a, **k: {
        "regime": "trending", "trend_direction": "bullish",
        "volatility_regime": "normal", "volatility_ratio_to_baseline": 1.0,
    })
    monkeypatch.setattr(engine, "analyze_market_regime_intelligence", lambda *a, **k: regime)
    monkeypatch.setattr(engine, "scan_symbol", lambda *a, **k: {
        "scenarios": [_scenario("bullish"), _scenario("bearish")]
    })
    monkeypatch.setattr(engine, "_make_plan", lambda *a, **k: {
        "rr_filter_passed": True, "entry": 100, "stop_loss": 95,
        "take_profits": [{"price": 110}, {"price": 115}, {"price": 120}],
    })


def test_regime_filter_is_opt_in_and_default_preserves_both_directions(monkeypatch):
    regime = {
        "aggregate_regime": "trending", "dominant_direction": "bullish",
        "volatility_state": "normal_volatility", "trend_alignment_count": 3,
    }
    _patch_engine(monkeypatch, regime)
    result = engine.generate_historical_smc_signals("BTCUSDT", _data())
    assert result["regime_filter"]["enabled"] is False
    assert {s["direction"] for s in result["signals"]} == {"bullish", "bearish"}


def test_enabled_filter_rejects_counter_trend_candidates(monkeypatch):
    regime = {
        "aggregate_regime": "trending", "dominant_direction": "bullish",
        "volatility_state": "normal_volatility", "trend_alignment_count": 3,
    }
    _patch_engine(monkeypatch, regime)
    result = engine.generate_historical_smc_signals(
        "BTCUSDT", _data(), use_regime_filter=True
    )
    assert {s["direction"] for s in result["signals"]} == {"bullish"}
    assert result["rejected_counts"]["regime_filter"] == 20
    assert result["signals"][0]["market_regime"]["aggregate_regime"] == "trending"


def test_enabled_filter_can_reject_transition_and_high_volatility(monkeypatch):
    regime = {
        "aggregate_regime": "transition", "dominant_direction": "neutral",
        "volatility_state": "high_volatility", "trend_alignment_count": 0,
    }
    _patch_engine(monkeypatch, regime)
    result = engine.generate_historical_smc_signals(
        "BTCUSDT", _data(), use_regime_filter=True,
        reject_transition_regime=True, reject_high_volatility=True,
    )
    assert result["signals"] == []
    assert result["rejected_counts"]["regime_filter"] == 40


def test_disabled_filter_still_reports_regime_context(monkeypatch):
    regime = {
        "aggregate_regime": "ranging", "dominant_direction": "neutral",
        "volatility_state": "low_volatility", "trend_alignment_count": 0,
    }
    _patch_engine(monkeypatch, regime)
    result = engine.generate_historical_smc_signals("BTCUSDT", _data())
    assert result["market_regime_summary"]["ranging"] > 0
    assert all(s["market_regime"]["aggregate_regime"] == "ranging" for s in result["signals"])
