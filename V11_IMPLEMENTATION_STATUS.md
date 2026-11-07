# SmartMoney V11 implementation status

## Implemented in this package
- Existing V1–V10 research code retained.
- V11 tenant store: users, sessions, portfolios, paper broker accounts, paper orders, audit events, shared-backtest history.
- PBKDF2 password hashing, random bearer tokens stored as SHA-256 hashes, 12-hour session expiry.
- Tenant ownership checks for all V11 portfolio/account/order/audit/backtest resources.
- Portfolio caps: maximum open positions, per-trade cash risk, aggregate open risk.
- Paper open/close lifecycle and realized P&L.
- Binance and MT5 paper-labelled accounts; both route to simulation only.
- Authenticated shared multi-symbol backtest endpoint using the retained V10 engine.
- Next.js `/v11` workspace for authentication, accounts, paper positions and portfolio risk.
- Unit tests for authentication, tenant isolation, order lifecycle, risk limits and backtest history.

## Not complete / must not be represented as complete
1. Legacy V1–V10 signals, settings and journal are not yet tenant-isolated.
2. MT5 terminal/EA bridge and Binance exchange order adapter are not connected.
3. Live execution is intentionally disabled.
4. Paper execution does not yet model exchange lot rules, margin, leverage, funding, swaps, spread, slippage or commission.
5. Strategy-generated historical signals, walk-forward validation, Monte Carlo and expanded calibration remain outstanding.
6. PostgreSQL/Redis are present in the Docker foundation but V11 storage currently uses SQLite; production migrations are outstanding.
7. Production-grade MFA, email verification, password reset, rate limiting, managed secrets, TLS, backup/restore drills and security/load testing remain outstanding.

## Local verification performed in build environment
- `python -m compileall -q app` — passed.
- `python -m pytest tests -q` — 75 passed.
- `from app.main import app` — V11 routes imported and registered.
- Frontend production build was not run in this build environment because frontend dependencies were not installed.
