# TRADF Phase 53–57 — Forex multi-market research and 21-day paper pilot

This patch extends the uploaded TRADF source. It does **not** enable live orders.

## Included

1. Eight FX/metal reference symbols already supported by the existing Frankfurter endpoint.
2. Intraday price stream using Twelve Data WebSocket, with UTC tick aggregation into real observed 1m, 5m, 15m, 1h and 4h OHLC bars. No bars are fabricated across missing intervals.
3. Shared SMC signal generation using the existing `historical_signal_engine` and `scan_symbol` path.
4. Historical download/import/backtest using Dukascopy's published bid M1 candles via `dukascopy-node`; M5/M15/H1/H4 bars are resampled only from complete contiguous M1 buckets.
5. Persistent 21-day Forex paper run, trade/event journal, portfolio ownership checks, USD conversion for JPY/CHF/CAD quote PnL, spread/slippage/commission simulation, expiry and stop endpoints.

## Important provider limits

- Historical download: Dukascopy data is historical bid-side data. The open-source `dukascopy-node` package is a downloader, not a broker quote or an execution venue.
- Live stream: Twelve Data Basic is free for testing but its WebSocket is trial-limited to up to eight permitted trial symbols. The worker will mark itself ready only if Twelve Data acknowledges **all eight** requested subscriptions. If any requested symbol is not available in the account's trial-symbol list (particularly XAU/USD), the worker will not become ready and the paper run start endpoint will refuse to start. Do not bypass this check.
- A free trial feed is not automatically licensed for a commercial multi-user trading product. Confirm the provider's display/non-display and redistribution terms before exposing data to customers.
- WebSocket price messages may be last/mid prices and do not guarantee bid/ask on every symbol. Paper fills therefore apply configurable spread and slippage assumptions. They are simulations, not broker fills.
- Dukascopy M1 history is used to create higher timeframes only when every constituent minute is present. Missing intervals are left missing; no synthetic candles are filled.
- Backtests run each instrument in an **isolated account denominated in its quote currency**. They are not a combined USD portfolio test. Review the JSON limitations and cost assumptions before relying on results.

## Install

Run PowerShell from the project root or pass `-ProjectRoot` explicitly. Set the project root once for the remaining commands:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& "$env:USERPROFILE\Downloads\TRADF_PHASE53_57_FOREX_21D\INSTALL_PHASE53_57.ps1" `
  -ProjectRoot "Q:\programing\website\New-bot\smartmoney-platform"
```

The installer creates a timestamped backup, copies new files, registers the API router and Alembic model metadata, and does not run migrations, deploy, commit or push.

## 1. Install dependencies and migrate Neon

```powershell
$Root = "Q:\programing\website\New-bot\smartmoney-platform"
```

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DIRECT_URL = "YOUR_NEON_DIRECT_URL"
.\.venv\Scripts\alembic.exe upgrade head
```

Use the actual Neon Direct URL as a local environment variable or in `backend/.env`; do not put it in source control. This migration adds Forex candle, paper-run, trade, event and worker-state tables. It does not delete the historical MT5 Alembic revision.

## 2. Download historical data (90 days by default)

Install Node.js/npm if not already installed. Run:

```powershell
& "$Root\backend\scripts\DOWNLOAD_FOREX_HISTORY.ps1" -Days 90 -ProjectRoot $Root
```

This downloads M1 bid CSVs for EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD and XAUUSD. The script creates `backend/data/forex/forex_costs.json` from the example if it does not exist.

The costs file uses raw price units. Its initial values are illustrative assumptions only; edit spread, slippage and commission to match the broker/account you intend to simulate. A broker has not yet been selected, so these values are not broker-verified.

## 3. Import candles into Neon

```powershell
Set-Location "$Root\backend"
.\.venv\Scripts\python.exe -m app.forex_history import-db --data-dir .\data\forex
```

The import requires at least 51 valid candles on each of the five timeframes for every symbol. It is idempotent and upserts by `(symbol,timeframe,candle_time)`.

## 4. Run historical SMC backtests

```powershell
.\.venv\Scripts\python.exe -m app.forex_history backtest `
  --data-dir .\data\forex `
  --costs .\data\forex\forex_costs.json `
  --output .\data\forex\backtest_results.json `
  --initial-equity 10000 `
  --risk-percent 0.25 `
  --min-quality-score 65 `
  --min-rr 2
```

Review `backtest_results.json` per symbol. Do not treat the eight independent account results as a portfolio curve or as proof of profitability. The backtest is research-only and `execution_allowed=false`.

## 5. Configure the live stream worker

Create a Twelve Data account and obtain an API key. Put it in `backend/.env` (not `.env.example`):

```dotenv
TWELVE_DATA_API_KEY=YOUR_REAL_KEY
```

Start the FastAPI API as usual. Start **one** separate, always-on background worker from `backend`:

```powershell
.\.venv\Scripts\python.exe -m app.forex_worker
```

In production, deploy the same command as a single background worker service. Do not run multiple replicas; the stream worker is intentionally single-instance. Keep it running continuously for the full test. The worker reconnects with backoff after disconnects and persists closed candles/trade events to Neon.

Check:

```text
GET /api/v1/forex/intraday/status
```

Proceed only when `worker.ready=true` and `subscribed_symbols` contains all eight symbols. If not, the free provider account does not permit the required symbol set and the 21-day run must not be started.

## 6. Start the 21-day paper run

You need an authenticated TRADF user and an existing portfolio. Get its ID from:

```text
GET /api/v1/v11/portfolios
```

Then call the API with the user's bearer token:

```http
POST /api/v1/forex/paper/start
Content-Type: application/json
Authorization: Bearer YOUR_USER_TOKEN
```

```json
{
  "portfolio_id": "YOUR_PORTFOLIO_ID",
  "risk_per_trade_pct": 0.25,
  "min_quality_score": 65,
  "min_rr": 2.0,
  "commission_pct": 0.0,
  "spread_bps": 1.5,
  "slippage_bps": 0.5,
  "confirm_paper_only": true
}
```

The API refuses to start unless:
- `TWELVE_DATA_API_KEY` is configured;
- the worker heartbeat is fresh and all eight symbols are acknowledged;
- the portfolio belongs to the authenticated user;
- at least 51 imported candles exist for every symbol/timeframe;
- no other Forex paper run is active for that portfolio;
- risk settings fit the portfolio's configured risk cap.

The 21-day clock starts when the API creates the run. At expiry the worker stops new entries and settles remaining paper positions on the next observed tick. If the worker is offline or the market is closed, final settlement can be delayed until the next tick.

Check status:

```http
GET /api/v1/forex/paper/status?portfolio_id=YOUR_PORTFOLIO_ID
Authorization: Bearer YOUR_USER_TOKEN
```

Stop early:

```http
POST /api/v1/forex/paper/YOUR_RUN_ID/stop
Authorization: Bearer YOUR_USER_TOKEN
```

## Tests

New tests:

```powershell
Set-Location "$Root\backend"
.\.venv\Scripts\python.exe -m pytest tests\test_forex_pipeline_phase53.py tests\test_forex_reference.py -q
```

The patch was locally checked against the uploaded source with 374 backend tests passing, excluding the five previously excluded DB/integration suites:
- `test_market_store_v9.py`
- `test_signal_journal_v6.py`
- `test_v11_platform.py`
- `test_execution_postgres.py`
- `test_forward_testing_postgres.py`

That local run does not replace running Alembic against your actual Neon database, verifying Twelve Data's eight subscriptions, or running the 21-day service continuously.

## Safety

- No broker API keys are used.
- No live orders are submitted.
- The paper engine only writes its own `tradf_forex_paper_*` journal.
- The 21-day test is an observation period, not a profitability certification.
- Do not deposit or allocate live capital based solely on this test.
