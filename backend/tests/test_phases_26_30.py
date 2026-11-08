import pytest

from app.phase26_paper_lifecycle import build_lifecycle_validation
from app.phase27_position_management import build_position_guidance
from app.phase28_market_intelligence import build_market_intelligence
from app.phase29_strategy_governance import rank_strategy_candidates
from app.phase30_release_validation import build_release_validation


def test_phase26_reconciles_closed_trade_and_journal():
    trades = [{
        "id": "t1", "status": "closed", "quantity": 1.0, "remaining_quantity": 0.0,
        "realized_pnl": 10.0, "fees_paid": 1.0, "avg_entry_price": 100.0,
    }]
    events = {"t1": [
        {"source_event_id": "entry", "sequence_no": 0, "event_type": "ENTRY_FILLED",
         "event_time_ms": 1000, "pnl": 0.0, "fee": 0.4, "quantity": 1.0},
        {"source_event_id": "exit", "sequence_no": 0, "event_type": "TP3_FILLED",
         "event_time_ms": 2000, "pnl": 10.0, "fee": 0.6, "quantity": 1.0},
    ]}
    result = build_lifecycle_validation(trades=trades, events_by_trade=events)
    assert result["status"] == "passed"
    assert result["realized_net_pnl"] == 9.0


def test_phase26_detects_pnl_mismatch():
    trades = [{"id": "t1", "status": "closed", "quantity": 1, "remaining_quantity": 0,
               "realized_pnl": 12, "fees_paid": 0, "avg_entry_price": 100}]
    events = {"t1": [{"source_event_id": "x", "sequence_no": 0, "event_type": "TP3_FILLED",
                      "event_time_ms": 1, "pnl": 10, "fee": 0, "quantity": 1}]}
    result = build_lifecycle_validation(trades=trades, events_by_trade=events)
    assert result["status"] == "review_required"
    assert "realized_pnl_mismatch" in {x["code"] for x in result["issues"]}


def test_phase27_produces_read_only_position_guidance():
    trades = [{"id": "t1", "symbol": "BTCUSDT", "side": "long", "status": "open",
               "avg_entry_price": 100, "initial_stop_loss": 95, "stop_loss": 99.8,
               "tp1": 110, "last_price": 100}]
    result = build_position_guidance(trades=trades, prices_by_trade_id={})
    assert result["position_count"] == 1
    assert "near stop-loss" in result["items"][0]["suggestions"][0].lower()
    assert result["execution_allowed"] is False


def _trend_candles(count=60):
    rows, price = [], 100.0
    for i in range(count):
        nxt = price + 0.3
        rows.append({"time": i * 300, "open": price, "high": nxt + 0.1,
                     "low": price - 0.1, "close": nxt, "volume": 10.0})
        price = nxt
    return rows


def test_phase28_uses_existing_market_regime_engine():
    result = build_market_intelligence(
        symbol="BTCUSDT", candles_by_timeframe={"5m": _trend_candles()}
    )
    assert result["symbol"] == "BTCUSDT"
    assert result["timeframes"]["5m"]["closed_candle_only"] is True
    assert result["execution_allowed"] is False


def test_phase28_rejects_unsupported_timeframe():
    with pytest.raises(ValueError, match="Unsupported"):
        build_market_intelligence(symbol="BTCUSDT", candles_by_timeframe={"2m": _trend_candles()})


def test_phase29_ranks_eligible_strategies_without_activation():
    result = rank_strategy_candidates(
        strategies=[{"strategy_id": "s1", "sample_size": 60,
                     "out_of_sample_expectancy_r": 0.2, "max_drawdown_pct": 8,
                     "stability_score": 0.8, "crowding_score": 0.1,
                     "market_regimes": ["trending"]}],
        market_regime="trending",
    )
    assert result["recommended_for_paper_validation"] == ["s1"]
    assert result["auto_activation"] is False


def test_phase29_rejects_duplicate_strategy_ids():
    item = {"strategy_id": "s1", "sample_size": 60, "out_of_sample_expectancy_r": .2,
            "max_drawdown_pct": 8, "stability_score": .8, "crowding_score": .1}
    with pytest.raises(ValueError, match="unique"):
        rank_strategy_candidates(strategies=[item, item])


def test_phase30_blocks_database_failure():
    lifecycle = {"status": "passed", "integrity_issue_count": 0}
    result = build_release_validation(database_probe_ok=False, lifecycle_report=lifecycle)
    assert result["status"] == "blocked"
    assert result["live_trading_enabled"] is False


def test_phase30_requires_review_when_lifecycle_has_issues():
    lifecycle = {"status": "review_required", "integrity_issue_count": 1}
    result = build_release_validation(database_probe_ok=True, lifecycle_report=lifecycle)
    assert result["status"] == "review_required"
