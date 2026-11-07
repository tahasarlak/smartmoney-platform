# SmartMoney V11 PostgreSQL foundation

This is the first, deliberately limited PostgreSQL/Alembic foundation.

## Decisions implemented
- Shared market prices and shared market watchlist.
- Signals support `public` and `private` visibility. Public signals have no owner; private signals require `user_id`.
- Clean initialization only: no SQLite data is imported.
- Paper-only broker accounts (`binance`, `mt5`).

## Install
From `backend`:
```bash
python -m pip install -r requirements-postgres.txt
```

## GitHub
Copy `.github/workflows/neon-initialize-schema.yml` into the repository.
Copy the contents of `backend/` into the repository's `backend/`.

Configure GitHub Environment `development` secret:
- `DIRECT_URL`: Neon direct (non-pooled) connection string for the development branch.

Run `SmartMoney V11 - Initialize Neon Schema` manually and enter:
`INITIALIZE_DEVELOPMENT`

The workflow refuses to run if application tables already exist in `public`. It creates tables only; it does not migrate the current application modules from SQLite.

## Important next step
The existing `market_store.py`, `signal_journal.py`, and `v11_platform.py` still use SQLite in the current source snapshot. Do not deploy this foundation as a completed PostgreSQL application. Next work must port those repositories/services to SQLAlchemy, add user ownership enforcement for private signals, and run the backend test suite against PostgreSQL.
