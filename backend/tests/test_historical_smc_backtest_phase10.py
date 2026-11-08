import pytest

from app import historical_smc_backtest as integration


def _candles():
    return [
        {"time": 1000 + i * 300, "open": 100, "high": 102, "low": 98, "close": 100}
        for i in range(4)
    ]


def _tf_data():
    return {tf: _candles() for tf in ("4h", "1h", "15m", "5m", "1m")}


def test_generates_smc_signals_and_sends_them_to_shared_backtester(monkeypatch):
    captured = {}

    def fake_generate(symbol, tf_data, **kwargs):
        return {
            "status": "completed",
            "signal_count": 1,
            "signals": [{
                "symbol": symbol,
                "index": 0,
                "direction": "bullish",
                "entry_reference": 100.0,
                "stop_loss": 95.0,
                "take_profit": 110.0,
                "execution_allowed": False,
            }],
        }

    def fake_backtest(candles, signals, **kwargs):
        captured["candles"] = candles
        captured["signals"] = signals
        captured["kwargs"] = kwargs
        return {"simulation_mode": "shared_portfolio", "trade_count": 0}

    monkeypatch.setattr(integration, "generate_historical_smc_signals", fake_generate)
    monkeypatch.setattr(integration, "run_multi_symbol_backtest", fake_backtest)

    result = integration.run_historical_smc_portfolio_backtest(
        {"btcusdt": _tf_data()}, initial_equity=10_000, risk_percent=0.5
    )

    assert result["generated_signal_count"] == 1
    assert captured["signals"][0]["quantity"] == pytest.approx(10.0)
    assert captured["signals"][0]["index"] == 0
    assert captured["candles"]["BTCUSDT"] == _candles()
    assert result["execution_allowed"] is False


def test_rejects_signal_that_claims_execution_permission(monkeypatch):
    monkeypatch.setattr(
        integration,
        "generate_historical_smc_signals",
        lambda *a, **k: {
            "status": "completed",
            "signal_count": 1,
            "signals": [{
                "index": 0, "direction": "bullish", "entry_reference": 100,
                "stop_loss": 95, "execution_allowed": True,
            }],
        },
    )
    with pytest.raises(ValueError, match="must not allow execution"):
        integration.run_historical_smc_portfolio_backtest({"BTCUSDT": _tf_data()})


def test_rejects_invalid_risk_budget():
    with pytest.raises(ValueError, match="risk_percent"):
        integration.run_historical_smc_portfolio_backtest(
            {"BTCUSDT": _tf_data()}, risk_percent=0
        )


def test_rejects_missing_timeframe_payload(monkeypatch):
    monkeypatch.setattr(
        integration,
        "generate_historical_smc_signals",
        lambda *a, **k: {"status": "completed", "signal_count": 0, "signals": []},
    )
    with pytest.raises(ValueError, match="Missing 5m"):
        integration.run_historical_smc_portfolio_backtest({"BTCUSDT": {"1m": _candles()}})
