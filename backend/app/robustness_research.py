"""Robustness stress diagnostics on persisted paper-trade outcomes.

This does not optimize strategy parameters or re-run signals on OHLC candles.
"""
from __future__ import annotations
import math
from typing import Any
from .walk_forward_validation import _trade_r, _timestamp, _metrics


def build_robustness_report(*, trades: list[dict[str, Any]], cost_stress_r: float = 0.05,
                            windows: int = 4) -> dict[str, Any]:
    if not isinstance(trades,list): raise ValueError("trades must be a list")
    if not 0 <= float(cost_stress_r) <= 1: raise ValueError("cost_stress_r must be between 0 and 1")
    if not 2 <= int(windows) <= 8: raise ValueError("windows must be between 2 and 8")
    rows=[]; skipped=0
    for t in trades:
        r=_trade_r(t); ts=_timestamp(t)
        if r is None or ts is None: skipped+=1; continue
        rows.append((ts,str(t.get("id","")),r))
    rows.sort(key=lambda x:(x[0],x[1]))
    values=[x[2] for x in rows]
    if not values:
        return {"status":"insufficient_sample","valid_trade_count":0,"skipped_trade_count":skipped,
                "base_metrics":_metrics([]),"stressed_metrics":_metrics([]),"windows":[],
                "robustness_score":None,"limitations":["No valid closed trades available."],"execution_allowed":False}
    stressed=[v-float(cost_stress_r) for v in values]
    chunks=[]
    for i in range(min(int(windows),len(values))):
        lo=i*len(values)//min(int(windows),len(values)); hi=(i+1)*len(values)//min(int(windows),len(values))
        chunk=values[lo:hi]
        if chunk: chunks.append({"window":i+1,**_metrics(chunk)})
    positive_windows=sum(1 for w in chunks if (w.get("mean_r") or 0)>0)
    base=sum(values)/len(values); stress=sum(stressed)/len(stressed)
    score=None
    if len(values)>=30:
        # Transparent diagnostic score, not a probability or industry-standard rating.
        score=max(0.0,min(100.0,50.0 + 25.0*(positive_windows/max(1,len(chunks))) + 25.0*max(-1,min(1,stress/(abs(base)+1e-9)))))
    return {"status":"completed" if len(values)>=30 else "insufficient_sample",
            "valid_trade_count":len(values),"skipped_trade_count":skipped,
            "base_metrics":_metrics(values),"stressed_metrics":_metrics(stressed),
            "cost_stress_r_per_trade":float(cost_stress_r),"windows":chunks,
            "positive_windows":positive_windows,"window_count":len(chunks),
            "robustness_score":round(score,2) if score is not None else None,
            "score_definition":"Heuristic diagnostic from positive chronological windows and mean R after fixed per-trade cost stress; not a calibrated probability.",
            "limitations":["This is outcome robustness analysis, not parameter perturbation or strategy re-optimization.",
                           "No historical OHLC signal re-generation is performed.",
                           "Fixed cost stress is a sensitivity assumption, not a measured execution-cost estimate.",
                           "Chronological windows may contain serially dependent trades."],
            "execution_allowed":False}
