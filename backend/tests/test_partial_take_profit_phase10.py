from __future__ import annotations

import pytest

from app.multi_backtesting import run_multi_symbol_backtest


def _rows(values):
    return [
        {"time": 1_800_000_000 + i * 300, "open": o, "high": h, "low": lo, "close": c}
        for i, (o, h, lo, c) in enumerate(values)
    ]


def test_partial_tp_ladder_closes_slices_and_moves_stop_to_break_even():
    candles = _rows([
        (100, 101, 99, 100),   # signal candle
        (100, 106, 99, 104),   # entry + TP1
        (104, 111, 101, 109),  # TP2; BE stop at 100 not touched
        (109, 116, 105, 114),  # TP3
    ])
    result = run_multi_symbol_backtest(
        {"BTCUSDT": candles},
        [{
            "symbol": "BTCUSDT", "index": 0, "direction": "bullish",
            "stop_loss": 95, "take_profit": 110, "quantity": 10,
            "take_profits": [
                {"price": 105, "fraction": 0.5},
                {"price": 110, "fraction": 0.3},
                {"price": 115, "fraction": 0.2},
            ],
            "break_even_after_tp1": True,
        }],
    )
    assert result["trade_count"] == 1
    trade = result["trades"][0]
    assert [x["reason"] for x in trade["partial_exits"]] == [
        "take_profit_1", "take_profit_2", "take_profit_3"
    ]
    assert [x["quantity"] for x in trade["partial_exits"]] == pytest.approx([5, 3, 2])
    assert trade["net_pnl"] == pytest.approx(85)
    assert trade["exit_reason"] == "take_profit_3"


def test_tp1_moves_stop_to_break_even_for_following_candles():
    candles = _rows([
        (100, 101, 99, 100),
        (100, 106, 99, 104),  # TP1
        (104, 106, 99, 100),  # BE stop touched; remaining 50% closes at entry
        (100, 101, 99, 100),
    ])
    result = run_multi_symbol_backtest(
        {"BTCUSDT": candles},
        [{
            "symbol": "BTCUSDT", "index": 0, "direction": "bullish",
            "stop_loss": 95, "take_profit": 110, "quantity": 10,
            "take_profits": [
                {"price": 105, "fraction": 0.5},
                {"price": 110, "fraction": 0.5},
            ],
        }],
    )
    trade = result["trades"][0]
    assert [x["reason"] for x in trade["partial_exits"]] == ["take_profit_1", "stop_loss"]
    assert trade["partial_exits"][1]["price"] == pytest.approx(100)
    assert trade["net_pnl"] == pytest.approx(25)


def test_stop_wins_when_stop_and_first_target_are_touched_same_candle():
    candles = _rows([
        (100, 101, 99, 100),
        (100, 106, 94, 100),
        (100, 101, 99, 100),
    ])
    result = run_multi_symbol_backtest(
        {"BTCUSDT": candles},
        [{
            "symbol": "BTCUSDT", "index": 0, "direction": "bullish",
            "stop_loss": 95, "take_profit": 110, "quantity": 2,
            "take_profits": [
                {"price": 105, "fraction": 0.5},
                {"price": 110, "fraction": 0.5},
            ],
        }],
    )
    trade = result["trades"][0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["partial_exits"][-1]["reason"] == "stop_loss"
    assert trade["net_pnl"] == pytest.approx(-10)


def test_partial_tp_fractions_must_sum_to_one():
    candles = _rows([(100, 101, 99, 100)] * 3)
    with pytest.raises(ValueError, match="sum to 1.0"):
        run_multi_symbol_backtest(
            {"BTCUSDT": candles},
            [{
                "symbol": "BTCUSDT", "index": 0, "direction": "bullish",
                "stop_loss": 95, "take_profit": 110, "quantity": 1,
                "take_profits": [
                    {"price": 105, "fraction": 0.4},
                    {"price": 110, "fraction": 0.4},
                ],
            }],
        )
