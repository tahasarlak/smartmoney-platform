from app.smc import analyze_smc

def make_candles(n=120):
    rows=[]
    p=100.0
    for i in range(n):
        op=p
        p += 0.25 if (i%10)<6 else -0.18
        rows.append({"time":i*60,"open":op,"high":max(op,p)+0.2,
                     "low":min(op,p)-0.2,"close":p,"volume":1})
    return rows

def test_analysis_uses_closed_candles_and_never_fakes_probability():
    result=analyze_smc("TEST",make_candles())
    assert result["closed_candle_only"] is True
    assert result["estimated_win_probability"] is None
    assert result["methodology_version"] == "smc-rule-engine-0.3"

def test_rejects_less_than_50_closed_candles():
    try:
        analyze_smc("TEST",make_candles(50))
    except ValueError:
        return
    assert False, "Expected validation error"

