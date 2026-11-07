# SmartMoney V11 bilingual update — audit and status

## Included in this package
- Existing SmartMoney V11 source tree and backend modules/tests.
- Persian/English language switch on the V11 workspace and authentication screen.
- Language preference persisted in browser localStorage.
- Persian uses RTL document direction; English uses LTR.
- Key V11 workspace labels, actions, notices, errors and account/order states are translated.
- Locale-aware cash/equity number formatting.
- RTL layout adjustments for header, forms, tables, account lists and risk rows.
- Paper-only execution boundary retained. Binance and MT5 remain paper-labelled account types.

## Verification performed for this source snapshot
- Backend test suite: 76 passed.
- Frontend production build: not verified in this environment because frontend dependency installation did not complete. Run `npm ci` then `npm run build` on the target Windows machine.
- The original V11 page and CSS were modified; backend behavior was not changed by the bilingual patch.

## Important existing product limitations (not silently marked complete)
- Binance is a public market-data provider in this build; V11 order execution is a local paper ledger, not an exchange demo/testnet order.
- MT5 is a paper account label/simulator only; no terminal or Expert Advisor bridge is connected.
- Legacy V1–V10 signals, settings and journals are not tenant-isolated.
- V11 uses SQLite locally; production PostgreSQL migration is outstanding.
- Password reset, email verification, MFA, login throttling, production session controls, TLS, managed secrets, operational monitoring, backup/restore drills and load/security testing remain outstanding.
- Strategy-generated backtesting, walk-forward validation, Monte Carlo and stronger calibration remain outstanding.
- Paper fills use user-supplied reference/exit prices and do not yet model broker lot rules, margin, leverage, funding, swaps, spread, slippage or commission.

## Safety
- Live trading remains disabled.
- No real broker order route is added.
- Never place broker/API secrets in frontend environment variables or source control.
- Use `.env.example` as a template; keep the real `.env` local and private.
