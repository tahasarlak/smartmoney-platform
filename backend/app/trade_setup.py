from __future__ import annotations
from typing import Any

def _atr(candles: list[dict[str, Any]], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    trs=[]
    for i in range(1,len(candles)):
        prev=candles[i-1]["close"]
        trs.append(max(candles[i]["high"]-candles[i]["low"],
                       abs(candles[i]["high"]-prev),
                       abs(candles[i]["low"]-prev)))
    values=trs[-period:]
    return sum(values)/len(values) if values else 0.0

def build_trade_setup(symbol: str, candles_by_tf: dict[str,list[dict[str,Any]]],
                      analyses: dict[str,dict[str,Any]], min_rr: float=2.0,
                      risk_percent: float=1.0, allow_counter_trend: bool=True) -> dict[str,Any]:
    """Build a research-only retest plan from a 5m unmitigated FVG/OB candidate."""
    if min_rr < 1:
        raise ValueError("min_rr must be at least 1.0")
    if not 0 < risk_percent <= 5:
        raise ValueError("risk_percent must be greater than 0 and at most 5")
    required=("4h","1h","15m","5m","1m")
    if any(tf not in candles_by_tf or len(candles_by_tf[tf]) < 51 for tf in required):
        raise ValueError("At least 51 candles are required for every timeframe")
    bias4=analyses["4h"].get("structure","range")
    bias1=analyses["1h"].get("structure","range")
    if bias4==bias1 and bias4 in ("bullish","bearish"):
        primary=bias4
        context="aligned"
    elif bias4 in ("bullish","bearish") and bias1=="range":
        primary=bias4
        context="partially_aligned"
    elif bias1 in ("bullish","bearish") and bias4=="range":
        primary=bias1
        context="partially_aligned"
    else:
        primary="range"
        context="conflicted_or_range"

    candidate=analyses["5m"]
    direction=candidate.get("directional_bias","range")
    if direction not in ("bullish","bearish"):
        return {"symbol":symbol,"status":"no_setup","reason":"5M has no directional structure",
                "entry":None,"stop_loss":None,"take_profits":[],"execution_allowed":False}
    counter=primary not in ("range",direction)
    if counter and not allow_counter_trend:
        return {"symbol":symbol,"status":"filtered_counter_trend",
                "reason":f"{direction} setup conflicts with {primary} higher-timeframe bias",
                "entry":None,"stop_loss":None,"take_profits":[],"execution_allowed":False}

    last=candles_by_tf["5m"][-2]  # only last closed candle
    price=float(last["close"])
    atr=_atr(candles_by_tf["5m"][:-1])
    if atr <= 0:
        return {"symbol":symbol,"status":"invalid_market_data","reason":"ATR could not be calculated",
                "entry":None,"stop_loss":None,"take_profits":[],"execution_allowed":False}
    zones=[]
    for z in candidate.get("zones",[]):
        if z.get("direction") != direction:
            continue
        if z.get("type") not in ("FVG","ORDER_BLOCK_CANDIDATE"):
            continue
        if z.get("status") not in ("unmitigated","candidate_requires_retest_and_validation"):
            continue
        try:
            lo,hi=float(z["low"]),float(z["high"])
        except (KeyError,TypeError,ValueError):
            continue
        if lo >= hi:
            continue
        # Ignore extremely wide zones. They are poor precision entry references.
        if (hi-lo)/atr > 2.5:
            continue
        # A retest zone must be on the correct side of current price.
        if direction=="bullish" and hi >= price:
            continue
        if direction=="bearish" and lo <= price:
            continue
        zones.append(z)
    if not zones:
        return {"symbol":symbol,"status":"watchlist",
                "reason":"No valid unmitigated 5M FVG/OB retest zone found on the setup side of price",
                "direction":direction,"current_price":price,"entry":None,
                "stop_loss":None,"take_profits":[],"execution_allowed":False}

    zone=sorted(zones,key=lambda z:abs(price-(float(z["low"])+float(z["high"]))/2))[0]
    low,high=float(zone["low"]),float(zone["high"])
    entry=(low+high)/2
    buffer=max(atr*0.15, price*0.0001)
    stop=low-buffer if direction=="bullish" else high+buffer
    risk=abs(entry-stop)
    if risk <= 0:
        return {"symbol":symbol,"status":"invalid_setup","reason":"Stop distance is zero",
                "entry":None,"stop_loss":None,"take_profits":[],"execution_allowed":False}
    targets=[]
    for multiple in (1.0,2.0,3.0):
        if direction=="bullish":
            target=entry+risk*multiple
        else:
            target=entry-risk*multiple
        targets.append({"name":f"TP{int(multiple)}","price":round(target,8),
                        "risk_reward":multiple})
    quality=int(candidate.get("quality_score",0))
    status="pending_retest" if ((direction=="bullish" and price>high) or
                                (direction=="bearish" and price<low)) else "zone_active"
    reasons=[
        f"5M {zone.get('type')} candidate provides a retest reference",
        f"Higher-timeframe context: {context}",
        "Entry is the midpoint of the selected zone",
        f"Stop includes a 0.15 ATR buffer; risk budget setting is {risk_percent}%"
    ]
    if counter:
        reasons.append("Counter-trend setup: elevated risk classification")
    return {
        "symbol":symbol,"status":status,"direction":direction,
        "setup_class":"counter_trend" if counter else ("aligned" if context=="aligned" else "mixed_context"),
        "quality_score":quality,"higher_timeframe_context":context,
        "zone":{"type":zone.get("type"),"low":low,"high":high,
                "formed_at":zone.get("formed_at"),"status":zone.get("status")},
        "current_price":round(price,8),"entry":round(entry,8),
        "stop_loss":round(stop,8),"risk_distance":round(risk,8),
        "take_profits":targets,"minimum_rr_requested":min_rr,
        "risk_percent_setting":risk_percent,
        "rr_filter_passed":3.0 >= min_rr,
        "estimated_win_probability":None,
        "probability_status":"unavailable_until_out_of_sample_calibration",
        "reasons":reasons,
        "invalidation":"Setup invalidates if price closes beyond the far side of the selected zone before entry.",
        "execution_allowed":False,
        "note":"Research-only plan. Position size requires account equity, contract specifications, fees and instrument-specific pip/tick value. No live or paper order is submitted."
    }
