from __future__ import annotations

import pytest

from app.market_regime_intelligence import analyze_market_regime_intelligence


def _series(tf, trend="up", volatility=1.0, count=70):
    rows = []
    price = 100.0
    for i in range(count):
        if trend == "up":
            price += 0.8
        elif trend == "down":
            price -= 0.8
        elif trend == "range":
            price += 0.8 if i % 2 == 0 else -0.8
        spread = max(0.05, volatility)
        rows.append({
            "time": 1_700_000_000 + i * 300,
            "open": price,
            "high": price + spread,
            "low": price - spread,
            "close": price,
            "volume": 100.0,
        })
    # Final row is treated as forming by the base analyzer.
    return rows


def test_aligned_trending_timeframes_produce_trend_following_context():
    data = {tf: _series(tf, "up") for tf in ("4h", "1h", "15m")}
    result = analyze_market_regime_intelligence(data, min_trend_alignment=2)
    assert result["aggregate_regime"] == "trending"
    assert result["dominant_direction"] == "bullish"
    assert result["strategy_policy"]["bias"] == "trend_following"
    assert result["execution_allowed"] is False


def test_opposing_timeframes_are_not_reported_as_aligned_trend():
    data = {
        "4h": _series("4h", "up"),
        "1h": _series("1h", "down"),
        "15m": _series("15m", "range"),
    }
    result = analyze_market_regime_intelligence(data, min_trend_alignment=2)
    assert result["aggregate_regime"] != "trending"
    assert result["strategy_policy"]["bias"] in {
        "wait_for_timeframe_alignment", "selective_or_wait"
    }


def test_ranging_context_gets_reduced_frequency_policy():
    data = {tf: _series(tf, "range") for tf in ("1h", "15m")}
    result = analyze_market_regime_intelligence(data)
    assert result["aggregate_regime"] == "ranging"
    assert result["strategy_policy"]["bias"] == "range_aware_reduced_frequency"
    assert result["strategy_policy"]["quality_score_adjustment"] < 0


def test_high_volatility_adds_conservative_policy_adjustment():
    data = {tf: _series(tf, "up", volatility=5.0) for tf in ("4h", "1h")}
    result = analyze_market_regime_intelligence(data)
    assert result["volatility_state"] in {"high_volatility", "normal_volatility"}
    if result["volatility_state"] == "high_volatility":
        assert result["strategy_policy"]["volatility_action"] == "reduce_risk_or_wait"
        assert result["strategy_policy"]["quality_score_adjustment"] <= 0


def test_final_forming_candle_does_not_change_closed_candle_regime():
    rows = _series("1h", "up")
    changed = [dict(row) for row in rows]
    changed[-1].update({"open": 10, "high": 1000, "low": 1, "close": 900})
    a = analyze_market_regime_intelligence({"1h": rows})
    b = analyze_market_regime_intelligence({"1h": changed})
    assert a["timeframe_reports"]["1h"] == b["timeframe_reports"]["1h"]


def test_rejects_unknown_timeframe():
    with pytest.raises(ValueError, match="Unsupported timeframes"):
        analyze_market_regime_intelligence({"2m": _series("2m")})


def test_rejects_invalid_alignment_threshold():
    with pytest.raises(ValueError, match="min_trend_alignment"):
        analyze_market_regime_intelligence({"1h": _series("1h")}, min_trend_alignment=0)
