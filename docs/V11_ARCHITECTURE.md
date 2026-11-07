# SmartMoney V11 architecture

## Decisions
- Multi-user product with tenant-scoped V11 data.
- Binance and MetaTrader 5 are represented as distinct broker account types.
- Both account types execute through the local paper ledger only.
- Live trading is disabled; there is no live order route in the V11 router.
- Shared portfolio risk and shared-equity multi-symbol backtesting are retained.

## Trust boundaries

1. Authentication issues random opaque bearer tokens. Only SHA-256 token hashes are stored. Passwords use PBKDF2-HMAC-SHA256 with a random salt.
2. V11 portfolio, account, paper-order, audit and backtest queries always include the authenticated `user_id` in ownership checks.
3. A portfolio owns multiple broker-labelled paper accounts. The aggregate open-position and aggregate open-risk limits are evaluated at portfolio scope, across all of its accounts.
4. The V11 paper ledger accepts a caller-supplied reference/exit price. It is a simulation input and must not be represented as an exchange fill or live quote.
5. The MT5 option is not a terminal connection. A separate, authenticated MT5 terminal/EA bridge remains a future adapter task.

## Current data model

- `v11_users`
- `v11_sessions`
- `v11_portfolios`
- `v11_broker_accounts`
- `v11_paper_orders`
- `v11_audit_events`
- `v11_backtest_runs`

SQLite is used for local V11 persistence. The database path can be overridden with `SMARTMONEY_V11_DB`.

## Remaining work before public multi-user deployment

- Move legacy signal journal, settings and scanner state into tenant-scoped stores.
- Add password reset, email verification, MFA, login throttling and session management UI.
- Add managed secret storage and broker credential encryption only when real broker credentials are introduced.
- Implement a tested MT5 Expert Advisor bridge and Binance demo/testnet order adapter.
- Add broker symbol metadata, lot/step sizes, contract multipliers, margin, leverage, funding, swaps, spread, slippage and commissions.
- Add strategy-generated historical signals, walk-forward splits, Monte Carlo and leakage checks.
- Move all tenant data to PostgreSQL and use Redis only for queues/cache where required.
- Add TLS, reverse proxy, rate limiting, backup/restore drills, monitoring and security/load tests.
