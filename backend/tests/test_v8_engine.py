from app.v8_engine import _find_duplicate_signal, _make_plan


def candles():
    rows = []
    price = 110.0
    for i in range(30):
        op = price
        price += 0.1
        rows.append({
            "time": i * 300,
            "open": op,
            "high": price + 0.2,
            "low": op - 0.2,
            "close": price,
            "volume": 1.0,
        })
    # The final row represents the still-forming candle.
    return rows


def test_make_bullish_plan_has_ordered_prices_and_no_probability():
    data = {"5m": candles()}
    scenario = {
        "direction": "bullish",
        "quality_score": 76,
        "confirmation": "confirmed_trigger",
        "setup_class": "aligned",
        "zone": {
            "type": "FVG",
            "low": 112.8,
            "high": 112.85,
            "formed_at": 100,
            "status": "unmitigated",
        },
        "reasons": ["15M liquidity sweep detected"],
    }
    plan = _make_plan("BTCUSDT", scenario, data, min_rr=2.0, risk_percent=0.5)
    assert plan is not None
    assert plan["stop_loss"] < plan["entry"] < plan["take_profits"][0]["price"]
    assert plan["take_profits"][1]["risk_reward"] == 2.0
    assert plan["estimated_win_probability"] is None
    assert plan["execution_allowed"] is False


def test_make_bearish_plan_has_ordered_prices():
    data = {"5m": candles()}
    scenario = {
        "direction": "bearish",
        "quality_score": 68,
        "confirmation": "developing",
        "setup_class": "counter_trend",
        "zone": {
            "type": "ORDER_BLOCK_CANDIDATE",
            "low": 112.97,
            "high": 112.99,
            "formed_at": 100,
            "status": "candidate_requires_retest_and_validation",
        },
        "reasons": [],
    }
    plan = _make_plan("ETHUSDT", scenario, data, min_rr=1.5, risk_percent=0.5)
    assert plan is not None
    assert plan["stop_loss"] > plan["entry"] > plan["take_profits"][0]["price"]
    assert plan["take_profits"][1]["risk_reward"] == 1.5


def test_plan_rejects_zone_on_wrong_side_of_price():
    data = {"5m": candles()}
    scenario = {
        "direction": "bullish",
        "quality_score": 80,
        "confirmation": "confirmed_trigger",
        "zone": {"type": "FVG", "low": 113.0, "high": 113.2},
    }
    assert _make_plan("BTCUSDT", scenario, data, 2.0, 0.5) is None


def test_duplicate_signal_is_detected_by_symbol_direction_and_zone():
    plan = {
        "symbol": "BTCUSDT",
        "direction": "bullish",
        "zone": {"low": 100.0, "high": 101.0},
    }

    def list_signals(status, symbol, limit):
        if status == "WAITING_ENTRY" and symbol == "BTCUSDT":
            return [{
                "id": "existing",
                "direction": "bullish",
                "zone_low": 100.0,
                "zone_high": 101.0,
            }]
        return []

    found = _find_duplicate_signal(list_signals, plan)
    assert found is not None
    assert found["id"] == "existing"


def test_scan_v8_returns_symbol_results_without_fake_probability():
    import asyncio
    from app.v8_engine import scan_symbols_v8

    now = 1_800_000_000
    intervals = {"4h": 14400, "1h": 3600, "15m": 900, "5m": 300, "1m": 60}

    def make_series(interval):
        rows = []
        start = now - interval * 101
        price = 100.0
        for i in range(101):
            op = price
            price += 0.01
            rows.append({
                "time": start + i * interval,
                "open": op,
                "high": price + 0.02,
                "low": op - 0.02,
                "close": price,
                "volume": 1.0,
            })
        return rows

    async def fetch(symbol, timeframe, limit):
        return make_series(intervals[timeframe])

    def analyze(symbol, rows, swing_length=3):
        return {
            "structure": "range",
            "directional_bias": "range",
            "quality_score": 30,
            "events": [],
            "zones": [],
        }

    result = asyncio.run(scan_symbols_v8(
        symbols=["BTCUSDT"],
        limit=100,
        fetch_klines=fetch,
        analyze_smc_fn=analyze,
        settings={"min_quality_score": 50, "min_rr": 2.0, "risk_per_trade_pct": 0.5},
        now_epoch=now,
    ))
    assert result["summary"]["scanned"] == 1
    assert result["summary"]["errors"] == 0
    assert result["results"][0]["market_regime"]["4h"]["closed_candle_only"] is True
    assert result["results"][0]["scenarios"][0]["regime_context"]["entry_timeframe"]["timeframe"] == "5m"
    assert result["summary"]["expanded_volatility_symbols"] >= 0
    assert result["estimated_win_probability"] is None
    assert result["execution_allowed"] is False


def test_make_plan_keeps_zone_currently_being_retested():
    data = {"5m": candles()}
    price = data["5m"][-2]["close"]
    scenario = {
        "direction": "bullish",
        "quality_score": 72,
        "confirmation": "developing",
        "setup_class": "aligned",
        "zone": {
            "type": "FVG",
            "low": price - 0.1,
            "high": price + 0.1,
            "formed_at": 100,
            "status": "unmitigated",
        },
        "reasons": [],
    }
    plan = _make_plan("BTCUSDT", scenario, data, 2.0, 0.5)
    assert plan is not None
    assert plan["status"] == "zone_active"



def test_make_plan_rejects_plan_after_tp1_was_already_crossed():
    data = {"5m": candles()}
    scenario = {
        "direction": "bearish",
        "quality_score": 75,
        "confirmation": "developing",
        "zone": {
            "type": "FVG",
            "low": 112.97,
            "high": 112.99,
            "formed_at": 100,
            "status": "unmitigated",
        },
        "reasons": [],
    }
    # Move the latest closed price below the bearish TP1.
    data["5m"][-2]["close"] = 112.0
    assert _make_plan("TESTUSDT", scenario, data, 2.0, 0.5) is None
