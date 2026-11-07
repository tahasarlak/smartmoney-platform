from typing import Any
from .smc import analyze_smc

TIMEFRAMES=("4h","1h","15m","5m","1m")

def _bias(result: dict[str,Any]) -> str:
    # Prefer confirmed swing structure; do not let equal-high/low context flip the trend.
    structure=result.get("structure","range")
    return structure if structure in ("bullish","bearish") else "range"

def analyze_multi_timeframe(symbol: str, candles_by_tf: dict[str,list[dict[str,Any]]],
                            min_rr: float=2.0, allow_counter_trend: bool=True) -> dict[str,Any]:
    analyses={}
    for tf in TIMEFRAMES:
        candles=candles_by_tf.get(tf,[])
        if len(candles)<51:
            raise ValueError(f"Not enough candles for {tf}: received {len(candles)}, need at least 51")
        analyses[tf]=analyze_smc(symbol,candles,swing_length=3)
    bias={tf:_bias(analyses[tf]) for tf in TIMEFRAMES}
    h4,h1=bias["4h"],bias["1h"]
    if h4==h1 and h4!="range":
        primary,context=h4,"aligned"
    elif h4!="range" and h1=="range":
        primary,context=h4,"partially_aligned"
    elif h1!="range" and h4=="range":
        primary,context=h1,"partially_aligned"
    elif h4!="range" and h1!="range" and h4!=h1:
        primary,context="range","conflicted"
    else:
        primary,context="range","conflicted_or_range"

    def has_event(tf,typ,direction):
        return any(e.get("type")==typ and e.get("direction")==direction for e in analyses[tf]["events"])
    def has_zone(tf,typ,direction):
        return any(z.get("type")==typ and z.get("direction")==direction and
                   z.get("status") in ("unmitigated","candidate_requires_retest_and_validation")
                   for z in analyses[tf]["zones"])
    candidates=[]
    for direction in ("bullish","bearish"):
        counter=primary not in ("range",direction)
        if counter and not allow_counter_trend: continue
        score,reasons=30,[]
        if primary==direction:
            score+=20
            reasons.append("4H and 1H structure aligned" if context=="aligned" else
                           "Only one higher timeframe has directional structure")
        elif counter:
            reasons.append(f"Counter-trend idea against {primary} higher-timeframe bias")
        else:
            reasons.append("4H/1H context is conflicting or ranging")
        if has_event("15m","LIQUIDITY_SWEEP",direction):
            score+=15; reasons.append("15M liquidity sweep detected")
        if has_event("5m","BOS",direction):
            score+=15; reasons.append("5M BOS detected")
        if has_event("5m","CHoCH",direction):
            score+=10; reasons.append("5M CHoCH detected")
        if has_zone("5m","FVG",direction):
            score+=8; reasons.append("5M unmitigated FVG candidate")
        if bias["15m"]==direction:
            score+=5; reasons.append("15M structure agrees")
        if bias["5m"]==direction:
            score+=5; reasons.append("5M structure agrees")
        if bias["1m"]==direction:
            score+=3; reasons.append("1M structure agrees")
        if counter: score-=8
        candidates.append({"direction":direction,"quality_score":max(0,min(100,score)),
                           "counter_trend":counter,"reasons":reasons})
    candidates.sort(key=lambda x:x["quality_score"],reverse=True)
    best=candidates[0]
    supported=has_event("15m","LIQUIDITY_SWEEP",best["direction"]) and (
        has_event("5m","BOS",best["direction"]) or has_event("5m","CHoCH",best["direction"]) or
        has_zone("5m","FVG",best["direction"]))
    state="developing_candidate" if best["quality_score"]>=65 and supported else (
        "watchlist" if best["quality_score"]>=45 else "no_qualified_setup")
    return {
        "symbol":symbol,
        "timeframes":{tf:{"structure":analyses[tf]["structure"],
                          "directional_bias":analyses[tf]["directional_bias"],
                          "quality_score":analyses[tf]["quality_score"],
                          "last_price":analyses[tf]["last_price"],
                          "events":analyses[tf]["events"],
                          "zones":analyses[tf]["zones"][-12:]} for tf in TIMEFRAMES},
        "higher_timeframe_context":context,"primary_bias":primary,
        "best_candidate":best,"candidate_state":state,
        "minimum_rr_requested":min_rr,"estimated_win_probability":None,
        "probability_status":"unavailable_until_out_of_sample_calibration",
        "entry_plan":None,"entry_plan_status":"not_generated_until_entry_and_stop_rules_are_validated",
        "execution_allowed":False,"methodology_version":"mtf-orchestrator-0.2",
        "note":"Research classification only; no entry, SL, TP or live order is generated."
    }
