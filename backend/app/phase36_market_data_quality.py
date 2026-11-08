"""Phase 36: market candle quality and freshness validation."""
from __future__ import annotations
import math
from typing import Any

TIMEFRAME_SECONDS={"1m":60,"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400}

def assess_candle_quality(*, candles: list[dict[str, Any]], timeframe: str,
                          now_seconds: int, stale_after_seconds: int = 1800) -> dict[str, Any]:
    if timeframe not in TIMEFRAME_SECONDS: raise ValueError("Unsupported timeframe")
    if not isinstance(candles,list) or len(candles)>2000: raise ValueError("candles must be a list of at most 2000")
    if now_seconds <= 0 or stale_after_seconds < 1: raise ValueError("Invalid clock or staleness threshold")
    issues=[]
    normalized=[]
    for i,c in enumerate(candles):
        try:
            t=int(c["time"]); o=float(c["open"]); h=float(c["high"]); l=float(c["low"]); cl=float(c["close"]); v=float(c.get("volume",0))
        except (KeyError,TypeError,ValueError,OverflowError):
            issues.append({"index":i,"code":"malformed_candle"}); continue
        if not all(math.isfinite(x) for x in (o,h,l,cl,v)) or min(o,h,l,cl)<=0 or v<0 or h<max(o,cl,l) or l>min(o,cl,h):
            issues.append({"index":i,"code":"invalid_ohlcv"}); continue
        normalized.append((t,o,h,l,cl,v))
    ordered=sorted(normalized,key=lambda x:x[0])
    times=[x[0] for x in ordered]
    if times != [x[0] for x in normalized]: issues.append({"code":"out_of_order"})
    if len(times)!=len(set(times)): issues.append({"code":"duplicate_timestamps"})
    gaps=0
    step=TIMEFRAME_SECONDS[timeframe]
    for a,b in zip(times,times[1:]):
        if b-a>step*1.5: gaps+=1
    if gaps: issues.append({"code":"candle_gaps","gap_count":gaps})
    latest=times[-1] if times else None
    age=now_seconds-latest if latest is not None else None
    if latest is None: issues.append({"code":"no_valid_candles"})
    elif age > stale_after_seconds: issues.append({"code":"stale_market_data","age_seconds":age})
    elif age < -step: issues.append({"code":"future_candle_timestamp","age_seconds":age})
    return {"status":"passed" if not issues else "degraded","timeframe":timeframe,
            "candles_received":len(candles),"candles_valid":len(normalized),
            "latest_candle_time":latest,"latest_candle_age_seconds":age,
            "gap_count":gaps,"issues":issues,"market_data_trusted":not issues,
            "execution_allowed":False}
