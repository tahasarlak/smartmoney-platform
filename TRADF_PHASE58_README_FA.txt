TRADF PHASE 58 — FINAL 21-DAY PAPER READINESS GATE
=================================================

This patch fixes three launch blockers found in the supplied repository:
1. Forex paper status contained a reference to an undefined variable.
2. The worker previously marked all eight symbols as ready after receiving any one tick.
3. Readiness did not persist or validate a fresh tick for each of the eight symbols.

WHAT IS INCLUDED
----------------
- Migration 0008: stores the last observed tick timestamp per Forex symbol.
- Strict worker readiness: all eight provider subscriptions must be confirmed and
  every symbol must have a fresh tick (maximum age: 180 seconds).
- Read-only GET /api/v1/forex/paper/preflight?portfolio_id=...
- Paper start now calls the preflight gate and refuses to start if any check fails.
- Fix for GET /api/v1/forex/paper/status.
- Four additional unit tests.
- Updated Neon migration workflow to verify revision 0008.

INSTALL
-------
Run PowerShell:

  $Root = "Q:\programing\website\New-bot\smartmoney-platform"
  Set-ExecutionPolicy -Scope Process Bypass -Force
  & "$env:USERPROFILE\Downloads\TRADF_PHASE58\INSTALL_PHASE58.ps1" -ProjectRoot $Root

The installer creates a timestamped backup before copying files.
It does NOT run migrations, deploy, commit, push, start the worker, or start a paper run.

AFTER INSTALL
-------------
1. Run backend tests:
   Set-Location "$Root\backend"
   .\.venv\Scripts\python.exe -m pytest -q `
     --ignore=tests/test_market_store_v9.py `
     --ignore=tests/test_signal_journal_v6.py `
     --ignore=tests/test_v11_platform.py `
     --ignore=tests/test_execution_postgres.py `
     --ignore=tests/test_forward_testing_postgres.py

2. Confirm migration head:
   .\.venv\Scripts\alembic.exe heads
   Expected: 0008_forex_worker_symbol_ticks (head)

3. Commit and push the patch. In GitHub Actions, run:
   TRADF Neon Database Migration
   confirmation = MIGRATE
   Wait for the workflow to verify revision 0008 and the per-symbol tick column.

4. Configure TWELVE_DATA_API_KEY as a secret/environment variable in BOTH:
   - the API service
   - the dedicated worker service

5. Deploy a separate, persistent backend worker process with command:
   python -m app.forex_worker
   Working directory: backend
   It must use the same Neon DATABASE_URL and TWELVE_DATA_API_KEY as the API.
   Do not run this as a short-lived GitHub Actions job. GitHub Actions is not a
   persistent 21-day worker host.

6. Confirm the worker status endpoint reports:
   status = ready
   ready = true
   all eight subscribed_symbols
   no stale_symbols
   Every symbol must have a fresh tick within 180 seconds.
   A provider plan that cannot subscribe to all eight symbols will remain blocked.

7. Import sufficient historical M1 data for all eight symbols, then confirm at
   least 50 complete candles exist for each symbol in each timeframe:
   1m, 5m, 15m, 1h, 4h.
   Existing history importer/backtest scripts remain the source of these candles.
   No synthetic bars are created to fill missing intervals.

8. Authenticate as a user and call:
   GET /api/v1/forex/paper/preflight?portfolio_id=YOUR_PORTFOLIO_ID

   Only continue if:
   status = READY_FOR_21D_PAPER
   ready_for_21d_paper = true
   blockers = []

9. Start explicitly in paper-only mode:
   POST /api/v1/forex/paper/start
   {
     "portfolio_id": "YOUR_PORTFOLIO_ID",
     "risk_per_trade_pct": 0.25,
     "min_quality_score": 65,
     "min_rr": 2.0,
     "commission_pct": 0.0,
     "spread_bps": 1.5,
     "slippage_bps": 0.5,
     "confirm_paper_only": true
   }

10. Save the returned run ID and verify the status endpoint regularly:
    GET /api/v1/forex/paper/status?portfolio_id=YOUR_PORTFOLIO_ID
    Use the returned run_id with POST /api/v1/forex/paper/{run_id}/stop if an
    intentional early stop is required.

IMPORTANT LIMITATIONS
---------------------
- The Twelve Data feed is a provider quote stream; availability and symbol access
  depend on the account's current plan and market hours.
- Paper fills are simulated from incoming prices and configured spread/slippage/
  commission assumptions. They are not broker fills.
- FX and metals markets have closed sessions. A per-symbol freshness gate can
  block startup while the market is closed or when the provider is not delivering
  all requested instruments.
- 21 calendar days are recorded from run start. Final settlement of open paper
  positions requires a subsequent real provider tick; no artificial prices are
  fabricated to force a close.
- No live trading or broker order route is enabled by this patch.
