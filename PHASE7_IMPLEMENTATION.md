# SmartMoney Phase 7 — Paper Forward Testing

## Goal

Phase 7 adds a persistent, tenant-scoped forward-testing engine. It evaluates research signals against accepted live Binance trade ticks and records simulated fills only. It does not create broker orders or enable live execution.

## Included

- Per-user forward-test runs attached to an owned portfolio and Binance paper account.
- Symbol allowlist, minimum signal quality, risk-per-trade, commission and adverse slippage settings.
- Optional import of already-active signals at run start. Default is `false`; otherwise only signals created after the run starts are eligible.
- Signal deduplication per run (`UNIQUE(run_id, signal_id)`).
- Market-tick entry fills; no candle look-ahead.
- Position sizing from configured risk cash divided by planned entry-to-stop distance.
- Partial exits: one third at TP1, one third at TP2, and the remainder at TP3.
- Conservative handling of a tick that gaps through the stop: stop is evaluated before targets.
- Entry and exit commissions plus adverse slippage on simulated fills.
- Per-event audit history and realized/unrealized performance summary.
- Stop semantics: a run stops importing new signals immediately but continues managing pending and open simulated trades until they finish.
- User/portfolio/account ownership checks and PostgreSQL migration `0002_phase7_forward_testing`.

## API

All endpoints are under `/api/v1/v11` and require the existing bearer token except the existing auth endpoints.

### Start

`POST /forward/runs`

```json
{
  "portfolio_id": "YOUR_PORTFOLIO_ID",
  "account_id": "YOUR_BINANCE_PAPER_ACCOUNT_ID",
  "symbols": ["BTCUSDT", "ETHUSDT"],
  "risk_per_trade_pct": 0.5,
  "min_quality_score": 70,
  "commission_pct": 0.04,
  "slippage_bps": 2,
  "include_existing_signals": false
}
```

### List runs

`GET /forward/runs?portfolio_id=...&limit=20`

### Stop importing new signals

`POST /forward/runs/{run_id}/stop`

The run enters `stopping` while pending/open trades remain. It changes to `stopped` after all tracked trades are terminal.

### Trades and event audit

- `GET /forward/runs/{run_id}/trades`
- `GET /forward/trades/{trade_id}/events`
- `GET /forward/runs/{run_id}/summary` — daily/weekly UTC PnL, realized and estimated unrealized PnL, fees and win/loss summary.
- `GET /forward/runs/{run_id}/comparison?backtest_run_id=...` — descriptive comparison with a saved backtest from the same portfolio.

## Fill and accounting rules

- Long entry triggers when an accepted trade tick is at or below planned entry; short entry triggers at or above planned entry.
- A tick already beyond the stop before entry is not opened as a paper trade.
- Long entry fills are worsened upward by slippage; short entry fills are worsened downward.
- Long exits are worsened downward; short exits are worsened upward.
- Commission is charged on entry notional and each partial exit notional.
- Net realized PnL includes entry and exit fees. Open PnL is an estimate using the last observed tick and estimated exit slippage/commission.
- Target fills use the observed market tick, not a fictional exact target-price fill.
- When a tick jumps through multiple targets, each remaining target tranche is filled at that observed tick price.
- `event_id` from Binance trade messages is used for per-trade duplicate-tick protection. Older timestamps are rejected.

## Operational notes and limitations

- The live monitor subscribes to symbols from active forward-test runs; symbol refresh follows the existing monitor refresh interval.
- This phase currently requires a Binance paper account because Binance public trade ticks are the only configured live market-data feed. The MT5 terminal/EA market-data bridge is not configured.
- Short positions are simulated against the same public price feed. No spot/derivatives margin, funding, liquidation or exchange lot-size model is claimed.
- This is not a probability model and does not produce a win-probability estimate.
- The existing portfolio/account `PaperOrder` workflow is unchanged; forward-test trades are stored in separate tables.
- No database reset is required. The GitHub PostgreSQL workflow applies the additive Alembic migration.
- Live execution remains disabled.

## Validation

Local installer checks:
- Python compile and app import.
- Offline forward-testing and existing regression tests.
- Alembic head check.

GitHub Actions checks:
- Neon pooled and direct connectivity.
- `alembic upgrade head`.
- Complete backend test suite, including tenant-scoped PostgreSQL integration tests.
- Presence of all three forward-testing tables, expected columns and migration head `0002_phase7_forward_testing`.
