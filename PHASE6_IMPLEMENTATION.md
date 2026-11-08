# SmartMoney Phase 6 — Strategy Validation

## Delivered

- `POST /api/v1/backtest/validate` accepts the existing multi-symbol shared-portfolio backtest input plus validation controls.
- Chronological rolling out-of-sample (OOS) replay: one initial-history block followed by 2–10 contiguous test folds.
- Fold reports include train-history/test boundaries, tested signal counts, and per-fold trade metrics. Positive-fold consistency uses all requested folds as its denominator, so empty folds are not silently discarded.
- Monte Carlo bootstrap of OOS trade PnL with deterministic seed, percentile bands, drawdown percentiles, and equity-depletion frequency.
- Execution-cost stress replay is performed independently inside each OOS fold, with the same fold boundaries, signals, initial-equity reset, and risk limits as the baseline.
- No database migration, reset, paper-order creation, or live execution is performed.

## API controls

- `folds`: 2–10, default 4.
- `monte_carlo_simulations`: 100–5000, default 1000.
- `random_seed`: deterministic unsigned 32-bit seed, default 42.
- `stress_cost_multiplier`: 1–10, default 2.

All existing shared-backtest controls remain available: candle series, signals, initial equity, trading costs, concurrency and loss limits.

## Important methodological limits

This phase performs rolling OOS replay of signals supplied by the caller. It does **not** retrain or optimize the signal generator in each training fold. A true walk-forward optimizer requires the strategy-generation function and an explicit parameter search space. Historical signals must have been generated without looking at future candles; the API cannot prove that from precomputed signals.

Each test fold is replayed independently from `initial_equity`; the aggregate OOS metrics summarize realized fold trades and are not a continuously compounded single-account equity curve. Accordingly, aggregate trade-sequence drawdown is reported as unavailable rather than fabricating a drawdown by concatenating independently reset folds. Use per-fold drawdown and Monte Carlo drawdown percentiles for diagnostics. Monte Carlo resamples fixed-currency trade PnL and is a robustness diagnostic, not a forecast, calibrated win probability, or guarantee. At least 30 OOS trades are a minimal warning threshold; 100+ across multiple regimes is preferable.

## Validation

Run locally:

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m pytest tests\test_strategy_validation.py tests\test_multi_backtesting_v10.py -v
```

The complete PostgreSQL integration suite must be run through the existing GitHub Actions workflow because the local workstation does not hold the Neon credentials.


## Phase 6 hardening

- Stress-cost replay now runs once per eligible OOS fold instead of combining all folds into one continuous portfolio.
- Aggregate OOS drawdown is intentionally `null`, because independent fold equity curves cannot be concatenated into a valid single-account drawdown.
- `positive_fold_ratio_pct` uses the requested fold count as its denominator; folds without eligible signals are not silently excluded.
- Stress output includes per-fold metrics and the worst fold drawdown.
