# SmartMoney V11 implementation status

## Implemented
- Existing V1–V10 research code retained.
- V11 tenant store backed by Neon PostgreSQL: users, sessions, portfolios, paper broker accounts, paper orders, audit events and shared-backtest history.
- PBKDF2 password hashing, random bearer tokens stored as SHA-256 hashes, 12-hour session expiry.
- Tenant ownership checks for V11 portfolio/account/order/audit/backtest resources.
- Portfolio caps: maximum open positions, per-trade cash risk and aggregate open risk.
- Paper open/close lifecycle and realized P&L.
- Shared market prices and market watchlist backed by PostgreSQL.
- Public/private signal journal and signal event history backed by PostgreSQL.
- Private signals require a real V11 user owner; trusted live monitor can update public and private signals.
- Alembic owns schema creation; app startup does not create schema.
- GitHub Actions validates Neon pooled/direct connections, applies migrations, runs backend tests and verifies schema.
- Next.js `/v11` workspace for authentication, accounts, paper positions and portfolio risk.

## Not complete / must not be represented as complete
1. MT5 terminal/EA bridge and Binance authenticated exchange order adapter are not connected.
2. Live execution is intentionally disabled.
3. Paper execution does not yet model exchange lot rules, margin, leverage, funding, swaps, spread, slippage or commission.
4. Strategy-generated historical signals, walk-forward validation, Monte Carlo and expanded calibration remain outstanding.
5. Production-grade MFA, email verification, password reset, rate limiting, managed secrets, production backup/restore drills and security/load testing remain outstanding.

## PostgreSQL Phase 2
- `DATABASE_URL` is the application pooled Neon URL.
- `DIRECT_URL` is the migration/admin Neon URL.
- Both must target the same database.
- The manual clean-initialization option drops and recreates the `public` schema only when explicitly confirmed.
- Normal pushes never reset the database.
