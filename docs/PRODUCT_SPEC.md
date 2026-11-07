# Product specification (initial)

## Product
A multi-market platform that analyses user-selected instruments with explicit SMC/ICT rule sets, explains every detected event, estimates outcomes only from validated historical evidence, and can later route approved orders to connected brokers/exchanges.

## Core principles
1. Opportunity-aware, not indiscriminately restrictive: show developing, valid, weak and counter-trend setups with clear labels.
2. Never fabricate win probabilities. Quality score and empirical probability are distinct fields.
3. Risk limits are enforced server-side and cannot be bypassed by aggressive presets.
4. Analysis and execution are separate services.
5. Every signal must be reproducible from candle data, rule version and settings snapshot.
6. Paper/demo first; live trading is a separately enabled, audited capability.

## Initial SMC vocabulary
- Swing highs/lows: local extrema using configurable left/right bars.
- BOS: close beyond a prior confirmed swing in the direction of current structure.
- CHoCH: close beyond the opposing protected swing against current structure.
- FVG: three-candle imbalance (bullish: candle 1 high < candle 3 low; bearish inverse).
- Order-block candidate: last opposing candle before a displacement leg that breaks a swing. This is a candidate, not an assertion of institutional orders.
- Liquidity pools: equal/near-equal confirmed swing highs/lows.
- Sweep: wick crosses a pool and candle closes back through it.
- Premium/discount: position relative to selected dealing range midpoint.

## Setup lifecycle
SCANNING -> DEVELOPING -> CONFIRMED -> ENTRY_READY -> PAPER_OPEN -> CLOSED / INVALIDATED / EXPIRED.
A signal is not an order. An execution policy separately checks risk, spread, market state, account permissions and user approval mode.

## Planned settings
Account: balance/equity basis, base risk %, max daily/weekly/monthly loss, max drawdown, max open trades, max aggregate open risk, consecutive-loss pause.
Strategy: enabled setup families, trend/counter-trend policy, allowed timeframes, minimum quality, minimum RR.
Execution: market/limit/stop, max spread, max slippage, duplicate prevention, partial exits, break-even, trailing stop, time exit.
Instrument overrides: risk, RR, sessions, setup filters and timeframe profile.
