from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any

@dataclass
class Pivot:
    index: int
    price: float
    kind: str

def _pivots(candles: list[dict[str, Any]], length: int) -> list[Pivot]:
    found = []
    for i in range(length, len(candles)-length):
        h, lo = candles[i]["high"], candles[i]["low"]
        if all(h > candles[j]["high"] for j in range(i-length, i+length+1) if j != i):
            found.append(Pivot(i, h, "high"))
        if all(lo < candles[j]["low"] for j in range(i-length, i+length+1) if j != i):
            found.append(Pivot(i, lo, "low"))
    return sorted(found, key=lambda p: p.index)

def _structure(highs: list[Pivot], lows: list[Pivot]) -> str:
    if len(highs) < 2 or len(lows) < 2:
        return "range"
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price
    if hh and hl: return "bullish"
    if lh and ll: return "bearish"
    return "range"

def _atr(c: list[dict[str, Any]], period: int = 14) -> float:
    values = []
    for i in range(1, len(c)):
        prev = c[i-1]["close"]
        values.append(max(c[i]["high"]-c[i]["low"],
                          abs(c[i]["high"]-prev), abs(c[i]["low"]-prev)))
    sample = values[-period:]
    return sum(sample)/len(sample) if sample else 0.0

def _fvg_zones(c: list[dict[str, Any]]) -> list[dict]:
    zones = []
    atr = _atr(c)
    for i in range(2, len(c)):
        a, impulse, b = c[i-2], c[i-1], c[i]
        body = abs(impulse["close"]-impulse["open"])
        prior = [abs(x["close"]-x["open"]) for x in c[max(0,i-22):i-1]]
        avg = sum(prior)/len(prior) if prior else 0
        if avg <= 0 or body < avg*1.15:
            continue
        if a["high"] < b["low"]:
            lo, hi, direction = a["high"], b["low"], "bullish"
            mitigated = any(x["low"] <= hi for x in c[i+1:])
        elif a["low"] > b["high"]:
            lo, hi, direction = b["high"], a["low"], "bearish"
            mitigated = any(x["high"] >= lo for x in c[i+1:])
        else:
            continue
        width = hi-lo
        width_atr = width/atr if atr else None
        zones.append({
            "type":"FVG", "direction":direction, "low":lo, "high":hi,
            "width":width, "width_atr":round(width_atr,3) if width_atr is not None else None,
            "formed_at":b["time"],
            "status":"mitigated" if mitigated else "unmitigated",
            "quality":"oversized_review" if width_atr is not None and width_atr > 2.5 else "normal"
        })
    return zones

def _liquidity(highs: list[Pivot], lows: list[Pivot], last: dict,
               tolerance_pct: float) -> list[dict]:
    events = []
    tolerance = tolerance_pct/100
    for pivots, pool, direction in ((highs,"BSL","bearish"),(lows,"SSL","bullish")):
        pair = None
        for bi in range(len(pivots)-1,0,-1):
            b = pivots[bi]
            for a in reversed(pivots[max(0,bi-5):bi]):
                if abs(a.price-b.price)/max(abs(a.price),1e-12) <= tolerance:
                    pair=(a,b); break
            if pair: break
        if not pair: continue
        a,b = pair
        level=(a.price+b.price)/2
        swept = (last["high"] > level and last["close"] < level) if pool=="BSL" else (
                 last["low"] < level and last["close"] > level)
        events.append({
            "type":"LIQUIDITY_SWEEP" if swept else "EQUAL_LEVELS",
            "direction":direction, "level":level, "time":last["time"],
            "pool":pool, "pivot_indices":[a.index,b.index]
        })
    return events

def _break_events(c: list[dict], highs: list[Pivot], lows: list[Pivot], structure: str) -> list[dict]:
    last=c[-1]
    out=[]
    if highs and last["close"] > highs[-1].price:
        out.append({"type":"BOS" if structure=="bullish" else "CHoCH",
                    "direction":"bullish","level":highs[-1].price,"time":last["time"]})
    if lows and last["close"] < lows[-1].price:
        out.append({"type":"BOS" if structure=="bearish" else "CHoCH",
                    "direction":"bearish","level":lows[-1].price,"time":last["time"]})
    return out

def _order_block(c: list[dict], events: list[dict]) -> list[dict]:
    # Only actual structure breaks may create an OB candidate.
    structure_events=[e for e in events if e.get("type") in ("BOS","CHoCH")]
    out=[]
    for event in structure_events:
        direction=event["direction"]
        idx=len(c)-1
        for j in range(idx-1,max(-1,idx-13),-1):
            candle=c[j]
            opposing=(candle["close"]<candle["open"]) if direction=="bullish" else (
                      candle["close"]>candle["open"])
            if opposing:
                candidate={"type":"ORDER_BLOCK_CANDIDATE","direction":direction,
                           "low":candle["low"],"high":candle["high"],
                           "formed_at":candle["time"],
                           "status":"candidate_requires_retest_and_validation"}
                key=(candidate["direction"],candidate["formed_at"],candidate["low"],candidate["high"])
                if not any((z["direction"],z["formed_at"],z["low"],z["high"])==key for z in out):
                    out.append(candidate)
                break
    return out

def analyze_smc(symbol: str, candles: list[dict[str, Any]], swing_length: int=3,
                equal_level_tolerance_pct: float=0.05) -> dict[str, Any]:
    if len(candles)<51:
        raise ValueError("At least 51 candles are required")
    c=sorted(candles,key=lambda x:x["time"])
    closed=c[:-1]  # Exclude current, still-forming candle.
    pivots=_pivots(closed,swing_length)
    highs=[p for p in pivots if p.kind=="high"]
    lows=[p for p in pivots if p.kind=="low"]
    last=closed[-1]
    structure=_structure(highs,lows)
    events=_break_events(closed,highs,lows,structure)
    events.extend(_liquidity(highs,lows,last,equal_level_tolerance_pct))
    zones=_fvg_zones(closed)
    zones.extend(_order_block(closed,events))

    # Equal liquidity pools are context only. They must not flip directional bias.
    structural=[e for e in events if e["type"] in ("BOS","CHoCH")]
    if structure in ("bullish","bearish"):
        direction=structure
    elif structural:
        direction=structural[-1]["direction"]
    else:
        direction="range"

    score=30
    if structure==direction and direction in ("bullish","bearish"): score+=20
    if any(e["type"]=="LIQUIDITY_SWEEP" and e["direction"]==direction for e in events): score+=20
    if any(e["type"] in ("BOS","CHoCH") and e["direction"]==direction for e in events): score+=15
    if any(z["type"]=="FVG" and z["direction"]==direction and z["status"]=="unmitigated" and z["quality"]=="normal" for z in zones): score+=10
    if any(z["type"]=="ORDER_BLOCK_CANDIDATE" and z["direction"]==direction for z in zones): score+=5
    return {
        "symbol":symbol,"last_price":last["close"],"structure":structure,
        "directional_bias":direction,"quality_score":min(100,score),
        "estimated_win_probability":None,
        "probability_status":"unavailable_until_out_of_sample_calibration",
        "events":events[-30:],"zones":zones[-40:],
        "pivots":[asdict(p) for p in pivots[-40:]],
        "closed_candle_only":True,"methodology_version":"smc-rule-engine-0.3",
        "disclaimer":"Rule-based SMC approximation. Signals require independent backtesting; not a trading instruction."
    }
