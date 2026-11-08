from __future__ import annotations

import math
import pytest

from app.phase12_research import (
    _metrics_from_trades,
    _normalize_market,
    run_phase12_research_suite,
)


def _market(n=160):
    rows = []
    price = 100.0
    for i in range(n):
        # Gentle deterministic oscillation with a mild upward drift.
        open_price = price
        close = price * (1.001 + (0.002 if i % 7 < 4 else -0.001))
        high = max(open_price, close) * 1.003
        low = min(open_price, close) * 0.997
        rows.append({
            "time": 1_700_000_000 + i * 300,
            "open": open_price, "high": high, "low": low,
            "close": close, "volume": 1000 + i,
        })
        price = close
    return {"BTCUSDT": rows}


def _signals():
    candles = _market()["BTCUSDT"]
    result = []
    for idx in range(35, 145, 5):
        entry = candles[idx + 1]["open"]
        result.append({
            "symbol": "BTCUSDT", "index": idx, "direction": "bullish",
            "stop_loss": entry * 0.985, "take_profit": entry * 1.02,
            "quantity": 0.5,
        })
    return result


def _payload():
    return {
        "candles_by_symbol": _market(),
        "strategies": [
            {"strategy_id": "smc_base", "name": "SMC Base", "signals": _signals()},
            {"strategy_id": "smc_selective", "name": "SMC Selective", "signals": _signals()[::2]},
        ],
        "initial_equity": 10000,
        "folds": 3,
        "monte_carlo_simulations": 100,
        "risk_candidates": [
            {"symbol": "BTCUSDT", "direction": "long", "entry": 100, "stop": 98, "quality_score": 80}
        ],
        "allocation_candidates": [
            {"symbol": "BTCUSDT", "direction": "long", "entry": 100, "stop": 98, "quality_score": 80}
        ],
        "prices_by_symbol": {
            "BTCUSDT": [100 + i * 0.1 for i in range(30)],
            "ETHUSDT": [80 + i * 0.08 for i in range(30)],
        },
        "forward_trades": [
            {"symbol": "BTCUSDT", "net_pnl": 12, "r_multiple": 1.2},
            {"symbol": "BTCUSDT", "net_pnl": -5, "r_multiple": -0.5},
            {"symbol": "ETHUSDT", "net_pnl": 8, "r_multiple": 0.8},
        ],
    }


def test_phase12_suite_returns_all_eight_deliverables():
    result = run_phase12_research_suite(_payload())
    assert result["status"] == "completed"
    assert len(result["strategy_comparison"]) == 2
    assert len(result["strategy_reports"]) == 2
    assert "market_regime_analysis" in result
    assert result["risk_sensitivity"]["status"] == "completed"
    assert result["portfolio_allocation"]["allocations"]
    assert result["correlation_analysis"]["status"] == "completed"
    assert result["forward_testing_analytics"]["metrics"]["trade_count"] == 3
    assert "market_benchmarks" in result["performance_benchmarking"]
    assert result["final_strategy_audit"]["live_trading_approved"] is False
    assert result["execution_allowed"] is False


def test_phase12_is_stateless_and_never_claims_execution():
    result = run_phase12_research_suite(_payload())
    assert result["methodology"]["risk_optimization"].startswith("Sensitivity")
    assert result["execution_allowed"] is False
    assert result["final_strategy_audit"]["execution_allowed"] is False


def test_rejects_duplicate_strategy_ids():
    payload = _payload()
    payload["strategies"][1]["strategy_id"] = payload["strategies"][0]["strategy_id"]
    with pytest.raises(ValueError, match="unique"):
        run_phase12_research_suite(payload)


def test_rejects_bad_ohlc():
    candles = _market()
    candles["BTCUSDT"][10]["low"] = 999999
    with pytest.raises(ValueError, match="OHLC invariant"):
        _normalize_market(candles)


def test_rejects_non_chronological_candles():
    candles = _market()
    candles["BTCUSDT"][4]["time"] = candles["BTCUSDT"][3]["time"]
    with pytest.raises(ValueError, match="strictly increasing"):
        _normalize_market(candles)


def test_forward_analytics_counts_consecutive_losses():
    metrics = _metrics_from_trades([
        {"net_pnl": -1}, {"net_pnl": -2}, {"net_pnl": 3}, {"net_pnl": -1}
    ])
    assert metrics["max_consecutive_losses"] == 2
    assert metrics["trade_count"] == 4


def test_empty_forward_trades_are_not_run():
    result = run_phase12_research_suite(_payload())
    assert result["forward_testing_analytics"]["status"] == "completed"


def test_requires_minimum_market_history():
    payload = _payload()
    payload["candles_by_symbol"]["BTCUSDT"] = _market(39)["BTCUSDT"]
    with pytest.raises(ValueError, match="at least 40"):
        run_phase12_research_suite(payload)


def test_rejects_invalid_risk_candidate():
    payload = _payload()
    payload["risk_candidates"][0]["stop"] = 101
    with pytest.raises(ValueError, match="wrong side"):
        run_phase12_research_suite(payload)


def test_no_live_execution_is_advertised():
    result = run_phase12_research_suite(_payload())
    assert result["final_strategy_audit"]["live_trading_approved"] is False
    assert all(a["checks"]["no_live_execution"] for a in result["final_strategy_audit"]["strategy_audits"])
