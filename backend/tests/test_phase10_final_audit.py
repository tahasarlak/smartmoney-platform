from __future__ import annotations

from app.phase10_final_audit import run_phase10_final_audit


def _candles(count=3):
    result = {}
    for tf, seconds in {
        "4h": 14_400, "1h": 3_600, "15m": 900, "5m": 300, "1m": 60
    }.items():
        result[tf] = [
            {
                "time": 1_700_000_000 + i * seconds,
                "open": 100 + i, "high": 102 + i,
                "low": 99 + i, "close": 101 + i,
                "volume": 100,
            }
            for i in range(count)
        ]
    return {"BTCUSDT": result}


def test_structural_audit_passes_and_does_not_claim_live_readiness():
    result = run_phase10_final_audit()
    assert result["status"] == "passed"
    assert result["failed_count"] == 0
    assert result["scope"]["profitability_certification"] is False
    assert result["scope"]["live_readiness_certification"] is False
    assert result["execution_allowed"] is False


def test_market_data_audit_passes_valid_ohlc():
    result = run_phase10_final_audit(_candles())
    market_check = next(item for item in result["checks"] if item["name"] == "market_data")
    assert market_check["status"] == "passed"


def test_market_data_audit_rejects_invalid_ohlc_relationship():
    data = _candles()
    data["BTCUSDT"]["5m"][1]["high"] = 1
    result = run_phase10_final_audit(data)
    assert result["status"] == "failed"
    market_check = next(item for item in result["checks"] if item["name"] == "market_data")
    assert market_check["status"] == "failed"
    assert "OHLC relationship" in market_check["detail"]


def test_market_data_audit_rejects_non_monotonic_timestamps():
    data = _candles()
    data["BTCUSDT"]["1m"][2]["time"] = data["BTCUSDT"]["1m"][1]["time"]
    result = run_phase10_final_audit(data)
    market_check = next(item for item in result["checks"] if item["name"] == "market_data")
    assert market_check["status"] == "failed"
    assert "strictly increasing" in market_check["detail"]


def test_market_data_audit_reports_missing_timeframe():
    data = _candles()
    del data["BTCUSDT"]["15m"]
    result = run_phase10_final_audit(data)
    market_check = next(item for item in result["checks"] if item["name"] == "market_data")
    assert market_check["status"] == "failed"
    assert "missing 15m" in market_check["detail"]


def test_audit_handles_empty_dataset():
    result = run_phase10_final_audit({})
    assert result["status"] == "failed"
    assert result["failed_count"] >= 1
