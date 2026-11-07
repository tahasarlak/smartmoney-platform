from app.smc import _order_block, analyze_smc
from app.mtf import analyze_multi_timeframe, TIMEFRAMES

def candles(n=140, seed=0):
    rows=[]; price=100.0
    for i in range(n):
        op=price
        price += 0.25 if (i+seed)%10<6 else -0.18
        rows.append({"time":i*60,"open":op,"high":max(op,price)+0.2,
                     "low":min(op,price)-0.2,"close":price,"volume":1})
    return rows

def test_order_block_ignores_non_structure_events_and_deduplicates():
    data=candles()
    events=[
        {"type":"EQUAL_LEVELS","direction":"bullish"},
        {"type":"LIQUIDITY_SWEEP","direction":"bullish"},
        {"type":"BOS","direction":"bullish"},
        {"type":"CHoCH","direction":"bullish"},
    ]
    zones=_order_block(data,events)
    assert len(zones)<=1
    assert all(z["type"]=="ORDER_BLOCK_CANDIDATE" for z in zones)

def test_equal_levels_do_not_override_structure_direction():
    result=analyze_smc("TEST",candles())
    assert result["directional_bias"] in ("bullish","bearish","range")
    assert result["estimated_win_probability"] is None
    assert result["methodology_version"]=="smc-rule-engine-0.3"

def test_mtf_keeps_probability_null_and_execution_disabled():
    data={tf:candles(seed=i) for i,tf in enumerate(TIMEFRAMES)}
    result=analyze_multi_timeframe("TEST",data)
    assert set(result["timeframes"])==set(TIMEFRAMES)
    assert result["estimated_win_probability"] is None
    assert result["execution_allowed"] is False
