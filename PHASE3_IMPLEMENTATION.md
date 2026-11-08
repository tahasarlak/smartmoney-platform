# SmartMoney Phase 3 — Integration Hardening

This bundle is a targeted Phase 3 integration pass based on the uploaded repository snapshot.

## Changes included

1. **Lazy live-monitor initialization**
   - Importing `app.main` no longer opens a PostgreSQL connection.
   - The watchlist and cached market prices are loaded when the monitor starts or a watchlist action is requested.
   - If PostgreSQL is temporarily unavailable at startup, the API process remains alive and the monitor retries initialization in its reconnect loop.

2. **FastAPI lifecycle**
   - Replaced deprecated startup/shutdown event handlers with the supported lifespan context.
   - Alembic remains the only schema owner; the application does not create tables on startup.

3. **Database readiness endpoint**
   - `GET /health` remains a process liveness check.
   - `GET /health/ready` executes `SELECT 1` against the configured PostgreSQL database and returns HTTP 503 if the database is unavailable.

4. **Signal lifecycle safety**
   - Older/out-of-order price ticks are ignored.
   - Terminal signals (`STOPPED`, `TP3_HIT`, and other non-active states) are immutable to later price updates.
   - Calibration outcomes include public signals only, preventing private user signals from entering the shared calibration dataset.

5. **Paper-order concurrency**
   - Paper-order admission now locks the owning portfolio row while checking open-position and risk limits.
   - Concurrent order requests for the same portfolio are serialized so they cannot both pass the same stale risk snapshot.

6. **Regression tests**
   - Added tests for stale-tick rejection and terminal-signal immutability.
   - Existing pure/offline tests and module import checks were run in the preparation environment.

## Validation performed

- Python compile check: passed.
- Import of `app.main`: passed without `DATABASE_URL` or `DIRECT_URL` configured.
- Offline test subset: **57 passed**.
- PostgreSQL integration tests were not run in this preparation environment because the Neon credentials are only available as GitHub Actions secrets. Run the GitHub Actions workflow after applying this bundle.

## Important scope boundary

This bundle does not enable live trading and does not claim to complete every production requirement. The uploaded repository itself still documents outstanding work including rate limiting, MFA/email verification, secrets management, backup/restore drills, load/security testing, broker adapters, and full walk-forward/Monte Carlo validation. Live execution remains disabled.


## Additional hardening applied in this completion pass

7. **Same-millisecond market ticks**
   - Ordered Binance trades can share the same millisecond timestamp. Signal updates now reject strictly older timestamps while accepting the next ordered tick at the same millisecond.
   - Added a regression test proving a signal can move from OPEN to TP1_HIT when both ticks share one timestamp.


8. **Non-blocking live monitor database work**
   - Startup preload, active-symbol discovery, market-price persistence, and signal updates are moved off the asyncio event loop using `asyncio.to_thread`.
   - Initialization is guarded by a thread lock to prevent concurrent duplicate preloads.
   - Status and market snapshot use the monitor's local cache and do not issue database queries on every health/status poll.

9. **Accurate monitor metrics**
   - `signals_updated` now increments only when a signal's status or recorded price actually changes, rather than counting every matching active signal returned by the journal.


## Repository review and completion-pass validation

The completion pass was checked against the uploaded repository snapshot.

- No `sqlite3` or `sqlite://` references remain in `backend/app`.
- PostgreSQL remains the only persistence layer for V11 users, portfolios, paper orders, signals, watchlist, and market prices.
- No database migration was added because this pass does not change the SQLAlchemy table schema.
- Added regression coverage for same-millisecond ordered ticks, monitor cache behavior, actual signal-update metrics, database readiness, and watchlist cache consistency after a failed database write.
- The focused offline suite (`test_phase3_hardening.py` and `test_live_price_monitor_v7.py`) passes locally. Neon-backed integration tests must still run in GitHub Actions because the database credentials are GitHub Environment secrets.
