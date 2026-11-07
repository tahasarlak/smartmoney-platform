from app.trade_setup import build_trade_setup

def candle_series(n=100, start=100.0, step=0.2):
    rows=[]
    p=start
    for i in range(n):
        op=p; p += step
        rows.append({"time":i*60,"open":op,"high":p+0.1,"low":op-0.1,"close":p,"volume":1})
    return rows

def test_returns_no_setup_without_directional_bias():
    data={tf:candle_series() for tf in ("4h","1h","15m","5m","1m")}
    analyses={tf:{"structure":"range","directional_bias":"range","zones":[]} for tf in data}
    result=build_trade_setup("TEST",data,analyses)
    assert result["status"]=="no_setup"
    assert result["execution_allowed"] is False

def test_builds_long_plan_from_valid_zone_and_never_claims_probability():
    data={tf:candle_series() for tf in ("4h","1h","15m","5m","1m")}
    # Keep a retest zone below current 5m close, with realistic width vs ATR.
    analyses={tf:{"structure":"bullish","directional_bias":"bullish","quality_score":70,"zones":[]} for tf in data}
    analyses["5m"]["zones"]=[{"type":"FVG","direction":"bullish","low":118.0,"high":118.2,
                               "status":"unmitigated","formed_at":5000}]
    result=build_trade_setup("TEST",data,analyses,min_rr=2.0,risk_percent=1.0)
    assert result["direction"]=="bullish"
    assert result["entry"] is not None and result["stop_loss"] < result["entry"]
    assert [x["name"] for x in result["take_profits"]]==["TP1","TP2","TP3"]
    assert result["estimated_win_probability"] is None
    assert result["execution_allowed"] is False

def test_rejects_invalid_rr():
    data={tf:candle_series() for tf in ("4h","1h","15m","5m","1m")}
    analyses={tf:{"structure":"bullish","zones":[]} for tf in data}
    try:
        build_trade_setup("TEST",data,analyses,min_rr=0.5)
    except ValueError:
        return
    assert False, "Expected ValueError"
