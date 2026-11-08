from __future__ import annotations

import pytest

from app import historical_smc_backtest as integration


def candles(rows):
    return [
        {"time": 1_800_000_000 + i * 300, "open": o, "high": h, "low": lo, "close": c}
        for i, (o, h, lo, c) in enumerate(rows)
    ]


def tf_data(rows):
    series = candles(rows)
    # All timeframes need chronological OHLC. The generator is replaced in
    # these tests, so the same deterministic rows are sufficient.
    return {tf: series for tf in ("4h", "1h", "15m", "5m", "1m")}


def generated_signal(symbol, *, index=0, direction="bullish", entry=100, stop=95, target=110):
    return {
        "status": "completed",
        "signal_count": 1,
        "signals": [{
            "symbol": symbol,
            "index": index,
            "direction": direction,
            "entry_reference": entry,
            "stop_loss": stop,
            "take_profit": target,
            "execution_allowed": False,
        }],
    }


def test_real_backtester_enters_on_next_candle_open_and_closes_at_target(monkeypatch):
    data = tf_data([
        (100, 101, 99, 100),  # signal candle
        (100, 111, 99, 105),  # next candle: entry at open, target reached
        (105, 106, 104, 105),
    ])
    monkeypatch.setattr(
        integration, "generate_historical_smc_signals",
        lambda symbol, *_a, **_k: generated_signal(symbol),
    )

    result = integration.run_historical_smc_portfolio_backtest(
        {"BTCUSDT": data}, initial_equity=10_000, risk_percent=0.5
    )

    assert result["trade_count"] == 1
    trade = result["trades"][0]
    assert trade["entry_time"] == data["5m"][1]["time"]
    assert trade["entry"] == pytest.approx(100)
    assert trade["exit_reason"] == "take_profit"
    assert trade["exit"] == pytest.approx(110)
    assert result["execution_allowed"] is False


def test_real_backtester_applies_costs_to_generated_trade(monkeypatch):
    data = tf_data([
        (100, 101, 99, 100),
        (100, 111, 99, 105),
        (105, 106, 104, 105),
    ])
    monkeypatch.setattr(
        integration, "generate_historical_smc_signals",
        lambda symbol, *_a, **_k: generated_signal(symbol),
    )

    result = integration.run_historical_smc_portfolio_backtest(
        {"BTCUSDT": data},
        initial_equity=10_000,
        risk_percent=0.5,
        spread=2,
        slippage=1,
        commission_pct=0.1,
    )
    trade = result["trades"][0]
    assert trade["entry"] == pytest.approx(102)
    assert trade["exit"] == pytest.approx(108)
    assert trade["fees"] > 0
    assert trade["net_pnl"] < trade["gross_pnl"]


def test_gap_that_invalidates_stop_target_geometry_is_rejected(monkeypatch):
    data = tf_data([
        (100, 101, 99, 100),
        (94, 96, 93, 95),  # gap below the long stop at 95
        (95, 96, 94, 95),
    ])
    monkeypatch.setattr(
        integration, "generate_historical_smc_signals",
        lambda symbol, *_a, **_k: generated_signal(symbol),
    )

    result = integration.run_historical_smc_portfolio_backtest({"BTCUSDT": data})
    assert result["trade_count"] == 0
    assert result["rejected_signals"][0]["reason"] == "invalid_levels_at_entry"


def test_multiple_symbols_share_one_portfolio(monkeypatch):
    rows = [
        (100, 101, 99, 100),
        (100, 111, 99, 105),
        (105, 106, 104, 105),
    ]
    monkeypatch.setattr(
        integration, "generate_historical_smc_signals",
        lambda symbol, *_a, **_k: generated_signal(symbol),
    )

    result = integration.run_historical_smc_portfolio_backtest(
        {"BTCUSDT": tf_data(rows), "ETHUSDT": tf_data(rows)},
        initial_equity=10_000,
        risk_percent=0.5,
        max_open_trades=2,
    )

    assert result["simulation_mode"] == "shared_portfolio"
    assert result["symbol_count"] == 2
    assert result["trade_count"] == 2
    assert result["initial_equity"] == 10_000
    assert result["execution_allowed"] is False
