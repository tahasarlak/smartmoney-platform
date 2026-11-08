"""Monte Carlo resampling of realized, closed paper-trade R multiples.

This is a descriptive scenario analysis, not a forecast or profitability guarantee.
"""
from __future__ import annotations
import math, random
from typing import Any
from .walk_forward_validation import _trade_r


def run_monte_carlo(*, trades: list[dict[str, Any]], simulations: int = 2000,
                    horizon: int = 100, seed: int = 17) -> dict[str, Any]:
    if not isinstance(trades, list):
        raise ValueError("trades must be a list")
    if not 500 <= int(simulations) <= 10000:
        raise ValueError("simulations must be between 500 and 10000")
    if not 10 <= int(horizon) <= 500:
        raise ValueError("horizon must be between 10 and 500")
    values = [r for t in trades if (r := _trade_r(t)) is not None and math.isfinite(r)]
    if len(values) < 10:
        return {"status":"insufficient_sample", "trade_count":len(values),
                "simulations":0, "horizon":horizon, "ending_r_quantiles":None,
                "max_drawdown_r_quantiles":None,
                "limitations":["At least 10 valid closed trades are required.",
                               "Bootstrap assumes observed trade outcomes are representative; serial dependence is not modeled."],
                "execution_allowed":False}
    rng=random.Random(seed)
    endings=[]; drawdowns=[]; positive=0
    for _ in range(int(simulations)):
        equity=0.0; peak=0.0; max_dd=0.0
        for _j in range(int(horizon)):
            equity += rng.choice(values)
            peak=max(peak,equity)
            max_dd=max(max_dd,peak-equity)
        endings.append(equity); drawdowns.append(max_dd)
        positive += equity > 0
    def qs(xs):
        xs=sorted(xs)
        def q(p): return round(xs[min(len(xs)-1,max(0,int((len(xs)-1)*p)))],6)
        return {"p05":q(.05),"p25":q(.25),"p50":q(.50),"p75":q(.75),"p95":q(.95)}
    return {"status":"completed", "trade_count":len(values), "simulations":int(simulations),
            "horizon_trades":int(horizon), "seed":int(seed),
            "ending_r_quantiles":qs(endings), "max_drawdown_r_quantiles":qs(drawdowns),
            "positive_ending_probability_pct":round(positive/int(simulations)*100,2),
            "observed_mean_r":round(sum(values)/len(values),6),
            "method":"iid_bootstrap_with_replacement_of_closed_trade_R_multiples",
            "limitations":["Scenario frequencies are not real-world probabilities or forecasts.",
                           "Trade ordering, volatility clustering, changing market regimes and parameter uncertainty are not modeled.",
                           "Only persisted closed paper execution trades are included."],
            "execution_allowed":False}
