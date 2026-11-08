from __future__ import annotations

import pytest

from app import historical_smc_walk_forward as wf


def _rows(count=18):
    return [
        {"time": 1_800_000_000 + i * 300, "open": 100, "high": 102, "low": 98, "close": 100}
        for i in range(count)
    ]


def _tf_data():
    rows = _rows()
    return {tf: rows for tf in ("4h", "1h", "15m", "5m", "1m")}


def _signal(symbol):
    return {
        "status": "completed",
        "signal_count": 1,
        "signals": [{
            "symbol": symbol, "index": 0, "direction": "bullish",
            "entry_reference": 100, "stop_loss": 95, "take_profit": 110,
            "execution_allowed": False,
        }],
    }


def test_generates_signals_and_delegates_to_chronological_validator(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        wf, "generate_historical_smc_signals",
        lambda symbol, *_a, **_k: _signal(symbol),
    )

    def fake_validate(candles, signals, **kwargs):
        captured["candles"] = candles
        captured["signals"] = signals
        captured["kwargs"] = kwargs
        return {"status": "completed", "fold_reports": [], "execution_allowed": False}

    monkeypatch.setattr(wf, "validate_strategy_walk_forward", fake_validate)

    result = wf.run_historical_smc_walk_forward({"btcusdt": _tf_data()}, folds=3)

    assert result["status"] == "completed"
    assert captured["signals"][0]["quantity"] == pytest.approx(10)
    assert captured["kwargs"]["folds"] == 3
    assert "BTCUSDT" in captured["candles"]
    assert result["execution_allowed"] is False
    assert result["validation_design"]["type"] == "chronological_rolling_out_of_sample"


def test_rejects_signal_with_execution_enabled(monkeypatch):
    bad = _signal("BTCUSDT")
    bad["signals"][0]["execution_allowed"] = True
    monkeypatch.setattr(wf, "generate_historical_smc_signals", lambda *_a, **_k: bad)

    with pytest.raises(ValueError, match="must not allow execution"):
        wf.run_historical_smc_walk_forward({"BTCUSDT": _tf_data()})


def test_rejects_bad_stop_target_geometry(monkeypatch):
    bad = _signal("BTCUSDT")
    bad["signals"][0]["take_profit"] = 99
    monkeypatch.setattr(wf, "generate_historical_smc_signals", lambda *_a, **_k: bad)

    with pytest.raises(ValueError, match="Invalid stop/target geometry"):
        wf.run_historical_smc_walk_forward({"BTCUSDT": _tf_data()})


def test_rejects_invalid_risk_percent():
    with pytest.raises(ValueError, match="risk_percent"):
        wf.run_historical_smc_walk_forward({"BTCUSDT": _tf_data()}, risk_percent=0)


def test_rejects_missing_5m_data():
    with pytest.raises(ValueError, match="Missing timeframe data or 5m"):
        wf.run_historical_smc_walk_forward({"BTCUSDT": {"1m": _rows()}})
