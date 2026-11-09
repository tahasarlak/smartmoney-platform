# TRADF Phases 47–52 — Risk Controls, Worker Health and Beginner UX

This additive patch is based on the uploaded `smartmoney-platform-main(6).zip` plus the Phase 40–46 production-safety package. It assumes Phases 40–46 have already been installed in the local project.

## Included

### Phase 47 — Testnet pre-trade limits
- Gross notional cap per Testnet order.
- Maximum count of open/ambiguous orders.
- Maximum aggregate gross notional relative to initial portfolio equity.
- Fail-closed validation of decimal inputs.
- These are order-notional controls, **not** a full position-risk, stop-loss, margin, or liquidation model.

Defaults:
- `TRADF_TESTNET_MAX_ORDER_NOTIONAL_USDT=50`
- `TRADF_TESTNET_MAX_OPEN_ORDERS=3`
- `TRADF_TESTNET_MAX_PORTFOLIO_EXPOSURE_PCT=10`

### Phase 48 — Testnet order reconciliation
- Authenticated endpoint: `POST /api/v1/v11/production/exchange/testnet/orders/reconcile?portfolio_id=...`
- Refreshes only persisted open/ambiguous Testnet orders using their deterministic client order IDs.
- Never resubmits orders.
- Stores a sanitized response only; never stores credentials or signatures in order response JSON.

### Phase 49 — Durable worker heartbeat
- Adds `tradf_worker_heartbeats` and Alembic revision `0005_tradf_worker_heartbeat`.
- Worker writes heartbeat, last-job time and process status.
- Authenticated endpoint: `GET /api/v1/v11/production/worker/status`.
- Stale threshold is `max(30 seconds, poll interval × 6)`.
- A healthy heartbeat does not grant permission to trade.

### Phase 50 — Beginner dashboard
- Replaces `/` with a Persian-first dashboard showing account value, recorded P&L, open positions and recorded portfolio risk.
- Uses existing authenticated portfolio data; does not invent a return forecast.

### Phase 51 — Simple portfolio setup
- Adds a short wizard to create a paper portfolio and optional paper account.
- Default new portfolio wizard budget is 500 USDT.
- The amount is simulated only; this does not deposit, transfer or invest real money.

### Phase 52 — Simple navigation and advanced workspace
- Preserves the previous terminal UI at `/advanced`.
- Keeps existing `/v11`, `/analytics`, `/reports`, `/strategies` and `/account` routes.
- The main page now has a short, non-technical navigation.

## Install

1. Extract the ZIP.
2. Open PowerShell in the extracted `TRADF_Phases_47_52` directory.
3. Run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\INSTALL_PHASE47_52.ps1
```

The installer expects the project at:
`Q:\programing\website\New-bot\smartmoney-platform`

It creates a timestamped backup before replacing files. It does not run migrations, deploy, commit or push.

## Test locally

```powershell
$Root = "Q:\programing\website\New-bot\smartmoney-platform"
Set-Location "$Root\backend"

.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe -m pytest tests\test_phase47_49_controls.py tests\test_production_infrastructure.py -q

.\.venv\Scripts\python.exe -m pytest -q `
  --ignore=tests/test_market_store_v9.py `
  --ignore=tests/test_signal_journal_v6.py `
  --ignore=tests/test_v11_platform.py `
  --ignore=tests/test_execution_postgres.py `
  --ignore=tests/test_forward_testing_postgres.py

Set-Location "$Root\frontend"
npm ci
npm run build
```

Database-dependent tests are intentionally not included in this local test command, per the current project workflow.

## Migration

The new revision follows `0004_tradf_production_infrastructure`:

`0005_tradf_worker_heartbeat`

Before applying it to Neon:
1. Confirm Neon backup/restore point.
2. Confirm the `0004` revision is already installed.
3. Review the SQL migration.
4. Only then run `alembic upgrade head` using the production database URL.

The new worker status endpoint returns `not_seen` until the worker has written its first heartbeat and the migration is applied.

## Render worker

Use a separate Render Background Worker from the same commit:
- Root directory: `backend`
- Start command: `python -m app.production_worker`
- Set the same `DATABASE_URL` and `TRADF_WORKER_POLL_SECONDS` as the API.
- Do not expose a public HTTP port.

Keep:
- `LIVE_TRADING_ENABLED=false`
- `TRADF_GLOBAL_KILL_SWITCH=true` during initial rollout
- `TRADF_TESTNET_TRADING_ENABLED=false` until a deliberate Testnet smoke test is approved

Never use production exchange API keys in this Testnet-only implementation.

## Important limitations

- The adapter remains Binance Spot Testnet only.
- The dashboard's P&L comes from persisted paper/execution portfolio summaries, not a prediction.
- The new notional caps are guardrails, not a complete risk engine.
- The worker heartbeat verifies process liveness only; it does not prove that every job completed correctly.
- The Testnet reconciliation endpoint reports unresolved exchange queries and does not automatically retry or resubmit.
- Live trading remains disabled. No phase in this patch authorizes live trading or guarantees profit.
- Independent security audit, production backup/restore test, and an extended paper/Testnet burn-in remain required.
