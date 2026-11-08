SMARTMONEY LIVE PRICE MONITOR 7.0

Prerequisite:
- Signal Journal 6.0 must already be installed and its imports/endpoints integrated.
- The v6 backend/app/signal_journal.py module and PostgreSQL schema (managed by Alembic) must exist.

Files:
- backend/app/live_price_monitor.py
- backend/tests/test_live_price_monitor_v7.py
- backend/LIVE_PRICE_MONITOR_7_PATCH.txt

Install:
1) Extract into project root.
2) Add import + startup/shutdown hooks + 3 endpoints from patch file to backend/app/main.py.
3) Ensure `websockets` package exists. `uvicorn[standard]` usually installs it.
   If missing: python -m pip install websockets
4) Run: python -m pytest tests -v
5) Restart uvicorn.

Monitor:
- Subscribes to Binance Spot @trade streams only for symbols with active journal signals.
- Refreshes subscriptions every 30 seconds.
- Reconnects after disconnects.
- Updates v6 journal from actual trade ticks.
- On process restart, active signals and watchlist entries are read back from PostgreSQL and subscriptions resume.
- This is a market-price monitor, not an order executor.
- It uses last trade price. It does not guarantee fill price or exchange execution.
- Candle high/low ambiguity is avoided because each update is a sequenced trade tick.
- It does not run if there are no active signals.
- Public deployment still needs authentication, rate limits, observability, persistent worker supervision,
  and per-user signal isolation.
