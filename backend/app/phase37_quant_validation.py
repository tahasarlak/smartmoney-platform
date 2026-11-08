"""Phase 37: quantitative diagnostics for supplied periodic returns."""
from __future__ import annotations
import math
from typing import Any

def validate_return_series(*, returns_pct: list[float], periods_per_year: int = 365,
                            minimum_observations: int = 30) -> dict[str, Any]:
    if not isinstance(returns_pct,list) or len(returns_pct)>10000: raise ValueError("returns_pct must contain at most 10000 observations")
    if periods_per_year<1 or not 5<=minimum_observations<=10000: raise ValueError("Invalid validation thresholds")
    values=[]
    for x in returns_pct:
        try: v=float(x)
        except (TypeError,ValueError,OverflowError): raise ValueError("Returns must be numeric")
        if not math.isfinite(v) or v<=-100: raise ValueError("Returns must be finite and greater than -100%")
        values.append(v/100)
    n=len(values)
    if not n:
        return {"status":"insufficient_sample","observations":0,"execution_allowed":False}
    equity=1.0; peak=1.0; max_dd=0.0
    for r in values:
        equity*=1+r
        peak=max(peak,equity)
        if peak>0: max_dd=max(max_dd,(peak-equity)/peak)
    mean=sum(values)/n
    variance=sum((x-mean)**2 for x in values)/(n-1) if n>1 else 0.0
    std=math.sqrt(variance)
    sharpe=(mean/std)*math.sqrt(periods_per_year) if std>0 else None
    wins=sum(1 for x in values if x>0)
    result={"status":"evaluated" if n>=minimum_observations else "insufficient_sample",
            "observations":n,"win_rate_pct":round(wins/n*100,4),
            "cumulative_return_pct":round((equity-1)*100,6),
            "max_drawdown_pct":round(max_dd*100,6),
            "annualized_sharpe":round(sharpe,4) if sharpe is not None else None,
            "mean_period_return_pct":round(mean*100,6),
            "periods_per_year":periods_per_year,
            "execution_allowed":False,
            "limitations":["Return observations are caller-supplied and are not independently reconciled with broker statements.",
                           "Annualized Sharpe assumes the supplied observations have the stated periodicity.",
                           "Historical statistics do not predict future returns."]}
    return result
