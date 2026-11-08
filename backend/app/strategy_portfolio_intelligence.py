"""Transparent correlation-aware weighting for supplied strategy research metrics."""
from __future__ import annotations
import math
from typing import Any


def allocate_strategy_weights(*, strategies: list[dict[str, Any]], correlation: list[list[float]] | None = None,
                              max_weight: float = 0.4, min_edge: float = 0.0) -> dict[str, Any]:
    if not isinstance(strategies, list) or not 1 <= len(strategies) <= 20:
        raise ValueError("strategies must contain 1 to 20 entries")
    if not 0 < float(max_weight) <= 1:
        raise ValueError("max_weight must be in (0, 1]")
    n = len(strategies)
    corr = correlation or [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    if len(corr) != n or any(not isinstance(row, list) or len(row) != n for row in corr):
        raise ValueError("correlation must be an NxN matrix matching strategies")
    matrix = []
    for i, row in enumerate(corr):
        vals=[]
        for j, raw in enumerate(row):
            v=float(raw)
            if not math.isfinite(v) or not -1 <= v <= 1: raise ValueError("correlations must be finite and within [-1,1]")
            if abs(v-float(corr[j][i])) > 1e-6: raise ValueError("correlation matrix must be symmetric")
            vals.append(v)
        matrix.append(vals)
    scores=[]
    for s in strategies:
        name=str(s.get("name", "")).strip()
        edge=float(s.get("expectancy_r", 0)); risk=float(s.get("risk_r", 1))
        if not name or not math.isfinite(edge) or not math.isfinite(risk) or risk <= 0:
            raise ValueError("Each strategy needs a name, finite expectancy_r and positive risk_r")
        scores.append(max(0.0, edge-float(min_edge))/risk)
    adjusted=[]
    for i, score in enumerate(scores):
        penalty=sum(max(0.0, matrix[i][j]) * scores[j] for j in range(n) if j != i) / max(sum(scores), 1e-12)
        adjusted.append(score/(1.0+penalty))
    active=[i for i,x in enumerate(adjusted) if x>0]
    weights=[0.0]*n
    remaining=1.0
    # Iterative capped proportional allocation. If all caps are reached, residual remains cash.
    while active and remaining>1e-12:
        total=sum(adjusted[i] for i in active)
        if total<=0: break
        capped=[]
        for i in active:
            proposed=remaining*adjusted[i]/total
            room=max(0.0,float(max_weight)-weights[i])
            if proposed>=room-1e-12:
                weights[i]+=room; remaining-=room; capped.append(i)
        if not capped:
            for i in active: weights[i]+=remaining*adjusted[i]/total
            remaining=0.0; break
        active=[i for i in active if i not in capped]
    rows=[{"name":str(strategies[i]["name"]),"score":round(scores[i],8),
           "correlation_adjusted_score":round(adjusted[i],8),"weight_pct":round(weights[i]*100,4)} for i in range(n)]
    return {"status":"completed","allocations":sorted(rows,key=lambda x:x["weight_pct"],reverse=True),
            "allocated_pct":round(sum(weights)*100,4),"cash_reserve_pct":round(max(0,1-sum(weights))*100,4),
            "max_weight_pct":round(float(max_weight)*100,4),"method":"positive_expectancy_risk_ratio_with_correlation_penalty",
            "execution_allowed":False,
            "limitations":["Inputs are user-supplied research metrics, not independently verified forecasts.",
                            "Correlation penalty is a heuristic, not full covariance optimization.",
                            "Weights are analytical suggestions only; no orders or transfers are created."]}
