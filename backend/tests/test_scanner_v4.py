from app.data_quality import validate_candle_series
from app.scanner import scan_symbol, TIMEFRAMES

def series(n=80, start=100.0, step=0.1, interval=60):
    out=[]; p=start
    for i in range(n):
        op=p; p += step
        out.append({"time":i*interval,"open":op,"high":max(op,p)+0.2,
                    "low":min(op,p)-0.2,"close":p,"volume":1})
    return out

def analyses():
    return {tf:{"structure":"range","directional_bias":"range","quality_score":30,
                "events":[],"zones":[]} for tf in TIMEFRAMES}

def test_scanner_returns_both_directions_and_never_fakes_probability():
    candles={tf:series(interval={"4h":14400,"1h":3600,"15m":900,"5m":300,"1m":60}[tf])
             for tf in TIMEFRAMES}
    result=scan_symbol("TEST",candles,analyses(),{"min_quality_score":35})
    assert len(result["scenarios"]) == 2
    assert result["estimated_win_probability"] is None
    assert result["execution_allowed"] is False

def test_scanner_can_surface_countertrend_zone_as_watchlist():
    candles={tf:series(interval={"4h":14400,"1h":3600,"15m":900,"5m":300,"1m":60}[tf])
             for tf in TIMEFRAMES}
    a=analyses()
    a["1h"]["structure"]="bearish"
    a["4h"]["structure"]="range"
    a["5m"]["zones"]=[{"type":"FVG","direction":"bullish","low":105.0,"high":105.2,
                       "status":"unmitigated","formed_at":123}]
    result=scan_symbol("TEST",candles,a,{"min_quality_score":30,"allow_counter_trend":True})
    bullish=[x for x in result["scenarios"] if x["direction"]=="bullish"]
    assert bullish
    assert bullish[0]["setup_class"]=="counter_trend"

def test_data_quality_rejects_duplicate_timestamps():
    rows=series(interval=300)
    rows[-1]["time"]=rows[-2]["time"]
    result=validate_candle_series(rows,"5m",now_epoch=100000)
    assert result["valid"] is False
    assert "Duplicate" in result["reason"]

def test_data_quality_accepts_fresh_closed_candle():
    rows=series(interval=300)
    # last closed candle open at 78*300; its close is 79*300
    result=validate_candle_series(rows,"5m",now_epoch=79*300+10)
    assert result["valid"] is True


def test_scanner_keeps_zone_when_price_is_currently_retesting_it():
    candles={tf:series(interval={"4h":14400,"1h":3600,"15m":900,"5m":300,"1m":60}[tf])
             for tf in TIMEFRAMES}
    a=analyses()
    price=candles["5m"][-2]["close"]
    a["5m"]["zones"]=[{"type":"FVG","direction":"bullish","low":price-0.05,
                       "high":price+0.05,"status":"unmitigated","formed_at":123}]
    result=scan_symbol("TEST",candles,a,{"min_quality_score":30})
    bullish=next(x for x in result["scenarios"] if x["direction"]=="bullish")
    assert bullish["zone"] is not None



def test_scanner_requires_latest_closed_retest_rejection_for_mitigated_fvg():
    candles = {
        tf: series(interval={"4h":14400,"1h":3600,"15m":900,"5m":300,"1m":60}[tf])
        for tf in TIMEFRAMES
    }
    rows = candles["5m"]
    last = rows[-2]
    previous = rows[-3]
    # Latest closed candle taps the bullish zone and closes above it.
    zone_low = last["close"] - 0.15
    zone_high = last["close"] - 0.05
    last["low"] = zone_low - 0.02
    last["high"] = last["close"] + 0.02
    last["open"] = last["close"] - 0.08
    a = analyses()
    a["5m"]["zones"] = [{
        "type": "FVG", "direction": "bullish",
        "low": zone_low, "high": zone_high,
        "status": "mitigated", "formed_at": 123,
    }]
    result = scan_symbol("TEST", candles, a, {"min_quality_score": 30})
    bullish = next(x for x in result["scenarios"] if x["direction"] == "bullish")
    assert bullish["zone"] is not None
    assert bullish["confirmation"] == "retest_detected_waiting_structure"

    # A same-candle structural break upgrades it to a confirmed trigger.
    a["5m"]["events"] = [{
        "type": "BOS", "direction": "bullish", "time": last["time"]
    }]
    result = scan_symbol("TEST", candles, a, {"min_quality_score": 30})
    bullish = next(x for x in result["scenarios"] if x["direction"] == "bullish")
    assert bullish["confirmation"] == "confirmed_trigger"


def test_scanner_ignores_old_mitigated_fvg_without_fresh_retest():
    candles = {
        tf: series(interval={"4h":14400,"1h":3600,"15m":900,"5m":300,"1m":60}[tf])
        for tf in TIMEFRAMES
    }
    price = candles["5m"][-2]["close"]
    a = analyses()
    a["5m"]["zones"] = [{
        "type": "FVG", "direction": "bullish",
        "low": price - 0.05, "high": price + 0.05,
        "status": "mitigated", "formed_at": 123,
    }]
    result = scan_symbol("TEST", candles, a, {"min_quality_score": 30})
    bullish = next(x for x in result["scenarios"] if x["direction"] == "bullish")
    assert bullish["zone"] is None
