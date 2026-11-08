# SmartMoney Phase 8 — Portfolio Intelligence & Risk Engine

## Scope

Phase 8 adds portfolio-level risk analytics without changing the database schema or enabling live execution.

### Added pure calculation module

`backend/app/risk_engine.py`

- Risk-based position sizing with an explicit notional cap.
- Pearson correlation matrix calculated from aligned simple-return series supplied by the caller.
- Portfolio risk assessment: aggregate stop-risk, per-position risk, symbol/direction breakdown, gross notional and remaining risk budget.
- Quality-score-weighted candidate allocation, bounded by remaining portfolio risk, per-trade risk and available position slots.

### Authenticated API

All routes are under `/api/v1/v11` and require the existing Bearer session:

- `POST /risk/position-size`
- `POST /risk/correlation`
- `GET /portfolios/{portfolio_id}/risk`
- `POST /portfolios/{portfolio_id}/risk/allocate`

Portfolio assessment reads only the authenticated user's portfolio, open paper orders, and open trades belonging to that user's active forward-test runs. Forward-test remaining risk is scaled by remaining quantity. Equity includes realized P&L from closed paper orders and forward-test runs.

## Safety and limitations

- This phase is analysis and sizing only. Every response explicitly returns `execution_allowed: false`.
- No broker API, exchange credentials, order submission, or live execution is introduced.
- No database migration is required.
- Correlation is historical Pearson correlation of simple returns, not a forecast. All series must be aligned and have equal length; insufficient/constant data is rejected or returned as unavailable.
- Capital allocation uses quality scores as relative weights, not win probabilities. Per-trade and portfolio caps are enforced. Correlation groups are labels only in this phase; the correlation endpoint supplies measured values separately.
- Notional is a simplified quote-value estimate (`quantity * entry`). Contract multipliers, margin, leverage, funding, swaps, lot increments, exchange filters and multi-currency conversion are not modeled yet.
- Existing paper order admission remains authoritative; this allocation endpoint does not create orders or reserve capital.

## Validation

Installer runs Python compilation, application import, and offline regression tests. Neon/PostgreSQL is not touched by this phase; existing GitHub Actions workflow remains the database integration gate.
