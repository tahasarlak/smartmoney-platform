# TRADF Phase 12 — Strategy Validation & Trading Intelligence

This single patch implements the Phase 12 research suite as one stateless API.
It reuses existing project functions from `strategy_validation`, `multi_backtesting`,
`market_regime`, and `risk_engine`; it does not create database tables or change
existing models.

## Deliverables

- 12.1 Multi-strategy walk-forward comparison
- 12.2 Candidate strategy ranking with an explicitly heuristic robustness score
- 12.3 Signal-entry market-regime attribution using closed-candle context
- 12.4 Risk sizing sensitivity scenarios (advisory; no auto-tuning)
- 12.5 Portfolio risk allocation using the existing allocator
- 12.6 Forward-test analytics from caller-supplied closed trade exports
- 12.7 Buy-and-hold market context benchmark
- 12.8 Final evidence audit; never approves live trading

## Install

Copy the three Python files from the patch:
- `backend/app/phase12_research.py`
- `backend/app/phase12_router.py`
- `backend/tests/test_phase12_research.py`

Then add the router to `backend/app/main.py` using the PowerShell anchor-safe
script in the chat instructions. Do not replace `main.py` wholesale.

## API

- `GET /api/v1/intelligence/phase12/capabilities`
- `POST /api/v1/intelligence/phase12/evaluate`

The evaluate request is stateless and uses caller-supplied data. It does not
connect to PostgreSQL or Binance.

## Request shape

```json
{
  "candles_by_symbol": {
    "BTCUSDT": [
      {"time": 1700000000, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000}
    ]
  },
  "strategies": [
    {
      "strategy_id": "smc_base",
      "name": "SMC Base",
      "signals": [
        {"symbol": "BTCUSDT", "index": 40, "direction": "bullish", "stop_loss": 98, "take_profit": 105, "quantity": 0.1}
      ]
    }
  ],
  "initial_equity": 10000,
  "folds": 3,
  "monte_carlo_simulations": 200,
  "risk_candidates": [
    {"symbol": "BTCUSDT", "direction": "long", "entry": 100, "stop": 98, "quality_score": 80}
  ],
  "allocation_candidates": [
    {"symbol": "BTCUSDT", "direction": "long", "entry": 100, "stop": 98, "quality_score": 80}
  ],
  "prices_by_symbol": {
    "BTCUSDT": [100, 101, 102],
    "ETHUSDT": [80, 81, 82]
  },
  "forward_trades": [
    {"symbol": "BTCUSDT", "net_pnl": 12, "r_multiple": 1.2}
  ]
}
```

The example arrays above are abbreviated; the service requires at least 40 candles
per symbol, and the existing walk-forward validator requires enough chronological
history for the requested folds. Signal indexes must have a following candle.
For useful Monte Carlo diagnostics, 10+ OOS trades are required; 100+ is preferred.

## Safety and interpretation

- All endpoints are research-only. `execution_allowed` is always false.
- The ranking score is a heuristic, not a probability or proof of profitability.
- The strategy validator consumes caller-supplied signals; it does not regenerate
  or optimize signals inside OOS folds.
- Regime buckets are independent replays and must not be added as one compounded
  portfolio curve.
- Strategy fold PnL and buy-and-hold percentage returns are not directly comparable.
- Forward analytics require caller-supplied closed trade records; there is no DB query.
- No live-trading approval is produced.
