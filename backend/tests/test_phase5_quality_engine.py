from __future__ import annotations

import pytest

from app.quality_engine import assess_signal_quality
from app.scanner import TIMEFRAMES, scan_symbol


def _analyses():
    return {
        tf: {"structure": "range", "events": [], "zones": []}
        for tf in TIMEFRAMES
    }


def _regimes():
    return {
        tf: {
            "regime": "transition",
            "trend_direction": "neutral",
            "volatility_regime": "normal",
            "volume_participation": "normal",
        }
        for tf in TIMEFRAMES
    }


def test_quality_assessment_never_claims_win_probability():
    result = assess_signal_quality(
        direction="bullish",
        technical_score=70,
        analyses=_analyses(),
        zone_valid=True,
        confirmation="confirmed_trigger",
        min_quality_score=60,
    )
    assert result["quality_score"] == 70
    assert result["grade"] == "good"
    assert result["review_eligible"] is True
    assert result["estimated_win_probability"] is None
    assert result["probability_status"].startswith("not_a_probability")


def test_regime_alignment_adds_evidence_and_conflict_reduces_score():
    analyses = _analyses()
    regimes = _regimes()
    regimes["4h"].update(regime="trending", trend_direction="bullish")
    regimes["15m"].update(regime="trending", trend_direction="bullish")

    aligned = assess_signal_quality(
        direction="bullish", technical_score=60, analyses=analyses,
        regimes=regimes, zone_valid=True, confirmation="developing",
    )
    assert aligned["quality_score"] == 66
    assert "market_regime" in aligned["confluence_groups"]

    regimes["4h"]["trend_direction"] = "bearish"
    conflicted = assess_signal_quality(
        direction="bullish", technical_score=60, analyses=analyses,
        regimes=regimes, zone_valid=True, confirmation="developing",
    )
    assert conflicted["quality_score"] < aligned["quality_score"]
    assert "4h_regime_conflict" in conflicted["risk_flags"]


def test_high_score_without_closed_trigger_is_not_review_eligible():
    result = assess_signal_quality(
        direction="bearish", technical_score=95, analyses=_analyses(),
        zone_valid=True, confirmation="retest_detected_waiting_structure",
        min_quality_score=50,
    )
    assert result["review_eligible"] is False
    assert result["classification"] == "watchlist_candidate"
    assert "structure_confirmation_missing" in result["risk_flags"]


def test_countertrend_without_trigger_is_flagged_as_elevated_false_signal_risk():
    result = assess_signal_quality(
        direction="bullish", technical_score=70, analyses=_analyses(),
        zone_valid=False, confirmation="no_valid_5m_entry_zone",
        counter_trend=True,
    )
    assert result["false_signal_risk"] == "elevated"
    assert "counter_trend_setup" in result["risk_flags"]
    assert result["review_eligible"] is False


def test_invalid_quality_inputs_are_rejected():
    with pytest.raises(ValueError):
        assess_signal_quality(
            direction="sideways", technical_score=50, analyses=_analyses()
        )
    with pytest.raises(ValueError):
        assess_signal_quality(
            direction="bullish", technical_score=101, analyses=_analyses()
        )
