from app.smc import analyze_smc

def test_smc_does_not_claim_probability():
    candles = []
    price = 100.0
    for i in range(100):
        o = price
        price += (0.2 if i % 7 < 4 else -0.1)
        candles.append({"time":i*60,"open":o,"high":max(o,price)+0.2,
                        "low":min(o,price)-0.2,"close":price,"volume":10})
    result = analyze_smc("TEST", candles)
    assert result["estimated_win_probability"] is None
    assert 0 <= result["quality_score"] <= 100
