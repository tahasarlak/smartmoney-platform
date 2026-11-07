# SmartMoney Platform — V9 foundation update

This patch is based on the uploaded New-bot2.zip source tree. It preserves the existing V8.2 scanner and adds tested foundations.

## Added in this patch

- SQLite-backed market watchlist and latest-price snapshots. Watchlist and latest prices survive API process restarts.
- The live monitor writes received Binance trade ticks to the market-state database and restores the saved watchlist/prices on process startup.
- Server-side risk preflight: per-trade risk, daily/weekly/monthly loss, drawdown, open-trade count, aggregate open risk and counter-trend policy.
- Conservative OHLC backtest replay: signal is entered no earlier than the next candle open; stop is assumed before target if both are touched in one candle; spread, slippage and commission can be specified.
- Evidence-gated calibration report based only on terminal journal outcomes (TP3_HIT vs STOPPED), with chronological 70/30 split, minimum holdout sample and score buckets. It does not publish probabilities until minimum sample requirements are met.
- API endpoints:
  - `POST /api/v1/risk/preflight`
  - `POST /api/v1/backtest/replay`
  - `GET /api/v1/intelligence/calibration/report`
- Added 11 automated tests.

## Important limitations — not represented as complete

1. The live monitor remains a Binance Spot trade-stream provider. EURUSD/forex is not a Binance instrument. A separate MT5 or licensed FX data adapter is still required.
2. The backtest endpoint is an execution replay engine. It accepts strategy signals as input; it does not yet generate historical V8/SMC signals over a walk-forward dataset.
3. Calibration uses closed journal outcomes only. It is not a trained predictive model, and a sufficiently large independent sample is required before bucket probabilities appear.
4. The risk preflight is a server-side calculation/check endpoint, not yet a mandatory broker execution gate. It assumes quantity is expressed in units whose price-risk is `abs(entry-stop) * quantity`; broker contract/tick-value conversion is not yet implemented.
5. No live broker order endpoint was added. MT5 Demo adapter, exchange testnet adapters, order reconciliation and broker-side stop management remain separate work.
6. Authentication, per-user data isolation, encrypted credential vault, PostgreSQL migrations and production deployment hardening remain incomplete.
7. The current frontend was not changed by this patch. The new endpoints are available in OpenAPI but are not yet exposed as full dashboard workflows.

## Safety

- `execution_allowed` remains false.
- This patch does not submit broker or exchange orders.
- Do not enable live trading based on these tests.
