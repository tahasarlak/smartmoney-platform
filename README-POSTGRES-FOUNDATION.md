# SmartMoney V11 PostgreSQL foundation — Phase 2

## Storage architecture
- Neon PostgreSQL is the shared persistent database for V11 users, sessions, portfolios, paper accounts, paper orders, audit events and shared-backtest history.
- Market prices and market watchlist are stored in PostgreSQL.
- Signals and signal events are stored in PostgreSQL. Public signals have no owner; private signals require an existing V11 user.
- SQLite is not used by these Phase 2 repositories.
- Alembic owns schema creation and upgrades. Application startup does not create or drop tables.
- `DATABASE_URL` is used by the application (prefer Neon pooled endpoint).
- `DIRECT_URL` is used by Alembic migrations and schema maintenance (Neon direct endpoint).
- Psycopg server-side prepared statements are disabled for PgBouncer transaction-pool compatibility.

## GitHub configuration
In GitHub → Settings → Environments → `development` configure:
- `DATABASE_URL`: Neon pooled PostgreSQL connection string.
- `DIRECT_URL`: Neon direct PostgreSQL connection string.

Both secrets must point to the same Neon database.

## Initialize or reset
The workflow `.github/workflows/smartmoney-postgres-tests.yml` runs migrations and the full backend test suite on pushes to `main`.

For a clean first initialization, run the workflow manually:
1. Set `reset_public_schema` to `true`.
2. Enter `RESET_PUBLIC_SCHEMA` in `reset_confirmation`.
3. Run the workflow.

This operation drops and recreates the entire `public` schema. All objects and data in that schema are permanently deleted. Do not use it after production data is stored.

For normal future deployments, run the workflow with `reset_public_schema=false`; Alembic applies pending migrations without deleting data.

## Verification
The workflow validates both Neon connections, imports and syntax, applies Alembic migrations, runs every test under `backend/tests`, and verifies the expected tables and Alembic revision.

## Boundaries
- Broker accounts remain paper-only. Live execution remains disabled.
- MT5 terminal/EA bridge and Binance authenticated order adapter are not connected.
- This phase completes the PostgreSQL storage and migration foundation; it does not claim MFA, email verification, password reset, rate limiting, managed secrets, production backup/restore drills, or load/security certification.
