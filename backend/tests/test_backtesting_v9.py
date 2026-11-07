import pytest
from app.backtesting import run_bar_backtest


def candles(rows, start=1_800_000_000, step=60):
    return [
        {"time": start + i * step, "open": o, "high": h, "low": lo, "close": c}
        for i, (o, h, lo, c) in enumerate(rows)
    ]


def test_signal_enters_only_on_next_candle_and_hits_target():
    data = candles([(100, 101, 99, 100), (100, 101, 99, 100), (100, 106, 99, 105)])
    result = run_bar_backtest(data, [{"index": 0, "direction": "bullish", "stop_loss": 98, "take_profit": 105}])
    assert result["trade_count"] == 1
    assert result["trades"][0]["entry_index"] == 1
    assert result["trades"][0]["exit_reason"] == "take_profit"


def test_stop_wins_when_stop_and_target_hit_same_bar():
    data = candles([(100, 101, 99, 100), (100, 106, 97, 101), (100, 101, 99, 100)])
    result = run_bar_backtest(data, [{"index": 0, "direction": "bullish", "stop_loss": 98, "take_profit": 105}])
    assert result["trades"][0]["exit_reason"] == "stop_loss"


def test_backtest_rejects_bad_ohlc():
    with pytest.raises(ValueError):
        run_bar_backtest([{"time": 1, "open": 10, "high": 9, "low": 8, "close": 9}], [],)


def test_multiple_signals_on_same_candle_are_not_overwritten():
    data = candles([(100, 101, 99, 100), (100, 101, 99, 100), (100, 106, 99, 105), (100, 101, 99, 100)])
    signals = [
        {"index": 0, "direction": "bullish", "stop_loss": 98, "take_profit": 105, "symbol": "A"},
        {"index": 0, "direction": "bullish", "stop_loss": 97, "take_profit": 104, "symbol": "B"},
    ]
    result = run_bar_backtest(data, signals, max_open_trades=2)
    assert result["trade_count"] == 2
    assert {t["symbol"] for t in result["trades"]} == {"A", "B"}


def test_max_open_trades_blocks_excess_same_bar_signals():
    data = candles([(100, 101, 99, 100), (100, 101, 99, 100), (100, 106, 99, 105), (100, 101, 99, 100)])
    signals = [
        {"index": 0, "direction": "bullish", "stop_loss": 98, "take_profit": 105},
        {"index": 0, "direction": "bullish", "stop_loss": 97, "take_profit": 104},
    ]
    result = run_bar_backtest(data, signals, max_open_trades=1)
    assert result["risk_controls"]["blocked_by_capacity"] == 1
    assert len(result["rejected_signals"]) == 1


def test_short_trade_is_supported():
    data = candles([(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 94, 95)])
    result = run_bar_backtest(data, [{"index": 0, "direction": "bearish", "stop_loss": 103, "take_profit": 95}])
    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "take_profit"


def test_equity_curve_contains_mark_to_market_values():
    data = candles([(100, 101, 99, 100), (100, 103, 99, 102), (102, 103, 101, 102)])
    result = run_bar_backtest(data, [{"index": 0, "direction": "bullish", "stop_loss": 98, "take_profit": 110}])
    assert len(result["equity_curve"]) == len(data)
    assert result["equity_curve"][1]["equity"] > 10000


def test_open_position_is_closed_at_end_of_data():
    data = candles([(100, 101, 99, 100), (100, 101, 99, 100), (101, 102, 100, 101)])
    result = run_bar_backtest(data, [{"index": 0, "direction": "bullish", "stop_loss": 98, "take_profit": 110}])
    assert result["trades"][0]["exit_reason"] == "end_of_data"


def test_invalid_max_open_trades_is_rejected():
    data = candles([(100, 101, 99, 100)] * 3)
    with pytest.raises(ValueError):
        run_bar_backtest(data, [], max_open_trades=0)


def test_daily_loss_limit_blocks_new_signals():
    data = candles([
        (100, 101, 99, 100),
        (100, 101, 97, 98),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
    ])

    signals = [
        {"index": 0, "direction": "bullish", "stop_loss": 98,
         "take_profit": 120, "quantity": 200},
        {"index": 1, "direction": "bullish", "stop_loss": 90,
         "take_profit": 120, "quantity": 1},
    ]

    result = run_bar_backtest(
        data, signals,
        max_daily_loss_pct=3,
        max_weekly_loss_pct=0,
    )

    assert result["risk_controls"]["blocked_by_daily_loss"] == 1
    assert result["rejected_signals"][0]["reason"] == "daily_loss_limit"


def test_weekly_loss_limit_blocks_new_signals():
    from datetime import datetime, timezone

    monday = int(datetime(2027, 1, 11, tzinfo=timezone.utc).timestamp())

    data = candles([
        (100, 101, 99, 100),
        (100, 101, 97, 98),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
    ], start=monday, step=86400)

    signals = [
        {"index": 0, "direction": "bullish", "stop_loss": 98,
         "take_profit": 120, "quantity": 200},
        {"index": 1, "direction": "bullish", "stop_loss": 90,
         "take_profit": 120, "quantity": 1},
    ]

    result = run_bar_backtest(
        data, signals,
        max_daily_loss_pct=0,
        max_weekly_loss_pct=3,
    )

    assert result["risk_controls"]["blocked_by_weekly_loss"] == 1
    assert result["rejected_signals"][0]["reason"] == "weekly_loss_limit"


def test_drawdown_limit_blocks_new_signals():
    data = candles([
        (100, 101, 99, 100),
        (100, 101, 97, 98),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
    ])

    signals = [
        {"index": 0, "direction": "bullish", "stop_loss": 98,
         "take_profit": 120, "quantity": 200},
        {"index": 1, "direction": "bullish", "stop_loss": 90,
         "take_profit": 120, "quantity": 1},
    ]

    result = run_bar_backtest(
        data, signals,
        max_daily_loss_pct=0,
        max_weekly_loss_pct=0,
        max_drawdown_pct=3,
    )

    assert result["risk_controls"]["blocked_by_drawdown"] == 1
    assert result["rejected_signals"][0]["reason"] == "max_drawdown_limit"


def test_long_trade_costs_are_calculated_correctly():
    data = candles([
        (100, 101, 99, 100),
        (100, 103, 99, 101),
        (101, 112, 100, 110),
    ])

    result = run_bar_backtest(
        data,
        [{
            "index": 0,
            "direction": "bullish",
            "stop_loss": 90,
            "take_profit": 120,
            "quantity": 2,
        }],
        spread=2,
        slippage=1,
        commission_pct=0.1,
    )

    trade = result["trades"][0]

    assert trade["entry"] == 102
    assert trade["exit"] == 108
    assert trade["gross_pnl"] == 12
    assert trade["fees"] == 0.42
    assert trade["net_pnl"] == 11.58


def test_short_trade_costs_are_calculated_correctly():
    data = candles([
        (100, 101, 99, 100),
        (100, 103, 99, 101),
        (99, 100, 88, 90),
    ])

    result = run_bar_backtest(
        data,
        [{
            "index": 0,
            "direction": "bearish",
            "stop_loss": 110,
            "take_profit": 80,
            "quantity": 2,
        }],
        spread=2,
        slippage=1,
        commission_pct=0.1,
    )

    trade = result["trades"][0]

    assert trade["entry"] == 98
    assert trade["exit"] == 92
    assert trade["gross_pnl"] == 12
    assert trade["fees"] == 0.38
    assert trade["net_pnl"] == 11.62


def test_open_position_equity_includes_estimated_exit_costs():
    data = candles([
        (100, 101, 99, 100),
        (100, 106, 99, 105),
        (105, 106, 100, 104),
    ])

    result = run_bar_backtest(
        data,
        [{
            "index": 0,
            "direction": "bullish",
            "stop_loss": 90,
            "take_profit": 120,
            "quantity": 2,
        }],
        spread=2,
        slippage=1,
        commission_pct=0.1,
    )

    # Entry = 102
    # Estimated exit = 103
    # Gross unrealized PnL = 2
    # Estimated commission = 0.41
    # Equity = 10001.59

    assert result["equity_curve"][1]["equity"] == 10001.59
