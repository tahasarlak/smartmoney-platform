# Safety and execution boundaries

- This repository starts in paper mode. `LIVE_TRADING_ENABLED=false` is required.
- No broker credentials are accepted by the initial UI/API.
- Do not expose API secrets to the browser or commit them to source control.
- Live trading must be implemented behind a separate execution service with per-user authorization, encrypted credentials, idempotency keys, audit trails, and a server-side kill switch.
- Risk is defined as planned loss at stop-loss, not notional position value.
- Position sizing must use instrument contract specifications, tick value, account currency conversion, lot step, min/max volume and broker stop-distance rules. The generic calculator here is an estimate and refuses unknown contract specs.
- Backtests must avoid look-ahead bias, include spread/commission/slippage, distinguish in-sample and out-of-sample data, and report sample size and uncertainty.
- Never display a numeric win probability without a validated calibration model and sufficient out-of-sample observations.
- A stop order cannot guarantee the exact exit price during gaps or illiquid conditions.
