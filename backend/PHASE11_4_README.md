# TRADF Phase 11.4 — Performance & Reliability

This patch is based on the uploaded `smartmoney-platform-main(14).zip`.

## Files in this patch

New:
- `backend/app/operational_resilience.py`
- `backend/tests/test_operational_resilience_phase11.py`

Updated:
- `backend/app/live_price_monitor.py`
- `backend/app/live_signal_monitor.py`
- `backend/app/main.py`

No database schema, Alembic migration, GitHub Actions workflow, credential, or exchange-order behavior is changed.

## Changes

- Binance WebSocket reconnect now uses capped exponential backoff with jitter.
- Live price monitor status exposes reconnect count/attempt, last connect/disconnect,
  next retry delay, and age of the last successfully persisted tick.
- Live SMC evaluation retries transient provider failures with bounded exponential delays.
- Live SMC monitor status exposes successful-cycle time, cycle duration,
  consecutive failed cycles, and retry count.
- Adds `GET /api/v1/monitor/operational-health`, a read-only process telemetry
  endpoint. It deliberately does not query PostgreSQL; database readiness remains
  available separately at `/health/ready`.
- Adds dependency-free resilience primitives and unit tests.

## Install

Extract the ZIP and copy the included files to the same relative paths in the
project. The three updated files are supplied as complete replacements, so take
a backup or ensure the working tree is clean before copying.

## Tests

Dedicated:
`python -m pytest tests/test_operational_resilience_phase11.py tests/test_live_signal_monitor_phase11.py tests/test_live_price_monitor_v7.py -q`

Full non-PostgreSQL suite (same exclusions used in the project):
`python -m pytest tests -q --ignore=tests/test_market_store_v9.py --ignore=tests/test_signal_journal_v6.py --ignore=tests/test_v11_platform.py --ignore=tests/test_execution_postgres.py --ignore=tests/test_forward_testing_postgres.py`

The PostgreSQL tests remain assigned to the existing GitHub Actions workflow.

## Safety

`execution_allowed` remains false. This patch does not create, enable, or submit
real or paper orders. It improves service reliability and observability only.
