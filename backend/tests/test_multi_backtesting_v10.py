import pytest
from app.multi_backtesting import run_multi_symbol_backtest


def rows(start, values):
    return [
        {"time": start + i * 60, "open": o, "high": h, "low": lo, "close": c}
        for i, (o, h, lo, c) in enumerate(values)
    ]


def test_multi_symbol_uses_shared_max_open_trade_limit():
    common = rows(1_800_000_000, [(100, 101, 99, 100)] * 4)
    result = run_multi_symbol_backtest(
        {"BTCUSDT": common, "ETHUSDT": common, "SOLUSDT": common},
        [
            {"symbol": "BTCUSDT", "index": 0, "direction": "bullish", "stop_loss": 90, "take_profit": 120},
            {"symbol": "ETHUSDT", "index": 0, "direction": "bullish", "stop_loss": 90, "take_profit": 120},
            {"symbol": "SOLUSDT", "index": 0, "direction": "bullish", "stop_loss": 90, "take_profit": 120},
        ],
        max_open_trades=2,
    )
    assert result["simulation_mode"] == "shared_portfolio"
    assert result["risk_controls"]["blocked_by_capacity"] == 1
    assert len(result["rejected_signals"]) == 1


def test_shared_equity_is_not_multiplied_by_symbol_count():
    data = rows(1_800_000_000, [(100, 101, 99, 100), (100, 101, 99, 100), (100, 106, 99, 105)])
    result = run_multi_symbol_backtest(
        {"BTCUSDT": data, "ETHUSDT": data},
        [
            {"symbol": "BTCUSDT", "index": 0, "direction": "bullish", "stop_loss": 98, "take_profit": 105, "quantity": 1},
            {"symbol": "ETHUSDT", "index": 0, "direction": "bullish", "stop_loss": 98, "take_profit": 105, "quantity": 1},
        ],
        initial_equity=10_000,
        max_open_trades=2,
    )
    assert result["trade_count"] == 2
    assert result["initial_equity"] == 10_000
    assert result["ending_equity"] == 10_010
    assert "ending_equity_sum" not in result


def test_signals_are_processed_in_global_time_order():
    btc = rows(1_800_000_000, [(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100), (100, 106, 99, 105)])
    eth = rows(1_800_000_060, [(200, 201, 199, 200), (200, 201, 199, 200), (200, 206, 199, 205)])
    result = run_multi_symbol_backtest(
        {"BTCUSDT": btc, "ETHUSDT": eth},
        [
            {"symbol": "ETHUSDT", "index": 0, "direction": "bullish", "stop_loss": 198, "take_profit": 205},
            {"symbol": "BTCUSDT", "index": 0, "direction": "bullish", "stop_loss": 98, "take_profit": 105},
        ],
        max_open_trades=1,
    )
    assert result["trades"][0]["symbol"] == "BTCUSDT"
    assert result["rejected_signals"][0]["symbol"] == "ETHUSDT"


def test_invalid_symbol_and_signal_are_rejected():
    data = rows(1_800_000_000, [(100, 101, 99, 100)] * 3)
    with pytest.raises(ValueError, match="unknown symbol"):
        run_multi_symbol_backtest(
            {"BTCUSDT": data},
            [{"symbol": "ETHUSDT", "index": 0, "direction": "bullish", "stop_loss": 90, "take_profit": 110}],
        )


def test_costs_are_applied_to_shared_portfolio_trades():
    data = rows(1_800_000_000, [(100, 101, 99, 100), (100, 103, 99, 101), (101, 112, 100, 110)])
    result = run_multi_symbol_backtest(
        {"BTCUSDT": data},
        [{"symbol": "BTCUSDT", "index": 0, "direction": "bullish", "stop_loss": 90, "take_profit": 120, "quantity": 2}],
        spread=2, slippage=1, commission_pct=0.1,
    )
    trade = result["trades"][0]
    assert trade["entry"] == 102
    assert trade["exit"] == 108
    assert trade["net_pnl"] == 11.58


def test_invalid_risk_settings_are_rejected():
    data = rows(1_800_000_000, [(100, 101, 99, 100)] * 3)
    with pytest.raises(ValueError):
        run_multi_symbol_backtest({"BTCUSDT": data}, [], max_open_trades=0)
