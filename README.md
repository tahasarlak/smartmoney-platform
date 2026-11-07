# SmartMoney Platform — starter repository

A modular, risk-first Smart Money / ICT research and paper-trading platform.

## Current scope
- Next.js dashboard (dark trading workspace).
- FastAPI backend with validated user trading settings.
- Multi-timeframe SMC analysis from OHLCV candles: pivots, market structure, BOS/CHoCH, FVG, basic order-block candidates, equal highs/lows and liquidity sweeps.
- Quality score is explicitly separate from estimated win probability.
- Position sizing and risk-limit checks.
- Public Binance market-data adapter for crypto candles.
- CSV OHLCV ingestion for offline/backtest workflows.
- Paper-trading mode only. Live execution is deliberately disabled until broker-specific validation, account isolation, secrets management, and demo testing are implemented.

## Important limitations
This is a working foundation, not a profitable strategy or a production-ready broker. The SMC definitions are configurable approximations and must be validated against the chosen market/data feed. The platform does **not** claim a win probability until a statistically adequate, out-of-sample calibration dataset exists. A quality score is not a probability.

## Run locally with Docker
1. Copy `.env.example` to `.env`.
2. Run `docker compose up --build`.
3. Frontend: http://localhost:3000
4. API docs: http://localhost:8000/docs
5. Health: http://localhost:8000/health

Without Docker:
- Backend: `cd backend && python -m venv .venv && pip install -r requirements.txt && uvicorn app.main:app --reload`
- Frontend: `cd frontend && npm install && npm run dev`

## API
- `GET /health`
- `GET /api/v1/settings/defaults`
- `PUT /api/v1/settings`
- `POST /api/v1/market/binance/klines`
- `POST /api/v1/analysis/smc`
- `POST /api/v1/risk/position-size`
- `POST /api/v1/execution/paper-order`

See `docs/PRODUCT_SPEC.md` and `docs/SAFETY.md`.

## Next implementation milestones
1. Add durable users/authentication and per-user encrypted broker credentials.
2. Add websocket market streaming and candle aggregation.
3. Add full multi-timeframe state machine and event persistence.
4. Add backtesting with spread, commission, slippage, walk-forward validation and probability calibration.
5. Add MT5 EA bridge and exchange adapters, initially on demo/testnet only.
6. Add audit logs, kill-switch, monitoring and deployment hardening.


## SmartMoney V11 — multi-user paper workspace

V11 adds a separate tenant-scoped workspace while retaining the V1–V10 research APIs:

- Email/password registration with PBKDF2 password hashing and opaque expiring bearer sessions.
- Per-user portfolios, broker-labelled paper accounts, paper positions, audit events and backtest history.
- Portfolio-level caps for open positions, per-trade risk and aggregate open risk.
- Binance and MetaTrader 5 paper account labels share the same simulation ledger; no live order is sent.
- Shared multi-symbol backtests can be saved and listed inside the authenticated user's portfolio.
- New Next.js workspace: `http://localhost:3000/v11`.

### V11 API

All routes below except `/system/readiness` and `/brokers` require `Authorization: Bearer <access_token>`:

- `POST /api/v1/v11/auth/register` — create user and default portfolio.
- `POST /api/v1/v11/auth/login` — create a 12-hour session.
- `GET /api/v1/v11/auth/me` — current user.
- `GET /api/v1/v11/portfolios` and `POST /api/v1/v11/portfolios`.
- `GET /api/v1/v11/portfolios/{portfolio_id}`.
- `GET /api/v1/v11/brokers` — broker capability/readiness declaration.
- `GET/POST /api/v1/v11/accounts` — create/list paper accounts.
- `GET/POST /api/v1/v11/paper/orders` — list/open paper positions.
- `POST /api/v1/v11/paper/orders/{order_id}/close` — close at a supplied simulated exit price.
- `POST/GET /api/v1/v11/backtests/shared` — run and persist a shared-equity multi-symbol replay.
- `GET /api/v1/v11/audit` — tenant-scoped audit events.
- `GET /api/v1/v11/system/readiness` — implementation/readiness report.

### Important V11 limitations — not production-ready

This release is a functional multi-user paper-trading foundation, not completion of all nine production phases. The legacy V1–V10 routes and signal journal have not yet been migrated to tenant-scoped storage; do not expose those legacy write/read routes to untrusted users. The V11 paper ledger is tenant-scoped. Binance public market data is available through the existing adapter, but Binance order execution is simulated. The MT5 account option is a local paper simulator label; a terminal/Expert Advisor bridge is not included or connected. Paper orders use a user-supplied reference price and do not yet model exchange-specific lot sizes, contract multipliers, margin, funding, swaps, slippage or commissions. Walk-forward validation, Monte Carlo, broker demo integration, production secret vault, PostgreSQL/Redis-backed persistence, TLS, rate limiting and deployment hardening remain outstanding. Live execution is disabled and is not exposed by V11.

The included SQLite V11 store is suitable for local development and controlled testing only. For production, migrate all tenant-owned data to PostgreSQL, enforce tenant ownership on every legacy endpoint, add a managed secret store and complete security/load testing before deployment.
