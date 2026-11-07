from app.mtf import analyze_multi_timeframe, TIMEFRAMES

def sample_candles(seed=0):
    rows, price = [], 100.0
    for i in range(160):
        op = price
        price += 0.12 if (i + seed) % 9 < 5 else -0.08
        rows.append({"time": i*60, "open": op, "high": max(op,price)+0.15,
                     "low": min(op,price)-0.15, "close": price, "volume": 10})
    return rows

def test_mtf_returns_all_timeframes_and_no_fake_probability():
    data = {tf: sample_candles(i) for i,tf in enumerate(TIMEFRAMES)}
    result = analyze_multi_timeframe("TEST", data)
    assert set(result["timeframes"]) == set(TIMEFRAMES)
    assert result["estimated_win_probability"] is None
    assert result["execution_allowed"] is False
    assert result["entry_plan"] is None
