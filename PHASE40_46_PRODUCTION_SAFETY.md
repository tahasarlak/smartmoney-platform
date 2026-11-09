# TRADF Phases 40–46 — Production Infrastructure & Safety

This patch is built against the uploaded `smartmoney-platform-main` source tree.
It is additive. It does not replace the existing paper-trading engine or enable live trading.

## Included phases

- **40 — Credential Vault:** Fernet authenticated encryption; keys are never returned after saving.
- **41 — Exchange Adapter:** Binance Spot Testnet only (`https://testnet.binance.vision`), signed HMAC requests, limit orders and cancellation.
- **42 — Durable Scheduler:** PostgreSQL-backed job leases using `FOR UPDATE SKIP LOCKED`; lease expiry allows recovery after worker restart.
- **43 — Kill Switch:** fail-closed global and per-user switches; activation attempts to cancel outstanding Testnet orders.
- **44 — Testnet Workflow:** explicit testnet acknowledgement, verified key permissions, idempotent client order IDs and persisted order intent.
- **45 — 21-day Paper Burn-in:** periodic snapshots, idempotent scheduled slots, observation duration and sample-count gate.
- **46 — Security Audit Support:** CI secret scan, Bandit, pip-audit, security snapshot endpoint and independent-audit handoff checklist.

## Hard safety boundaries

1. The adapter base URL is a constant pointing only to Binance Spot Testnet. There is no live exchange URL or live-order implementation in this patch.
2. `LIVE_TRADING_ENABLED` must remain `false`.
3. `TRADF_GLOBAL_KILL_SWITCH` defaults to `true`.
4. `TRADF_TESTNET_TRADING_ENABLED` defaults to `false`.
5. User kill switch defaults to enabled. Resume is a separate explicit API action.
6. Testnet order placement is limit-only and requires `confirm_testnet_only=true`.
7. The scheduler only snapshots existing persisted paper-trade state. It does not create exchange orders or automatically trade.
8. The 21-day burn-in gate also requires 100 samples, no excessive sample gap, a recent worker heartbeat and at least 30 closed paper trades. It is an operational observation gate, not proof of profitability.
9. CI scans and the in-app snapshot are not an independent penetration test. A qualified external security review is still required before any live-capital product.

## Important source compatibility blocker found in the uploaded ZIP

The supplied source archive has a pre-existing import mismatch: `backend/app/main.py`,
`backend/app/phase12_research.py`, and `backend/app/historical_smc_walk_forward.py`
import `validate_strategy_walk_forward`, but the supplied
`backend/app/strategy_validation.py` defines `build_strategy_validation` and does not
define `validate_strategy_walk_forward`. Importing `app.main` from this exact archive
fails before the API can start. The installer therefore checks for that function and
stops before copying files if it is still absent. Use the matching working source from
your current GitHub/deployment checkout or resolve that separate baseline defect first.
This patch deliberately does not invent a replacement backtesting algorithm.

## Install prerequisites

The uploaded source should contain:
- `backend/app/main.py`
- `backend/app/v11_platform.py`
- `backend/app/db_models.py`
- `backend/app/database.py`
- `backend/migrations/versions/0003_phase9_paper_execution.py`
- `frontend/app/globals.css`

## Install (PowerShell)

Save the ZIP as:
`$env:USERPROFILE\Downloads\TRADF_Phases_40_46_Production_Safety.zip`

Then run the installer printed in the assistant response or the `INSTALL_PHASE40_46.ps1` file included in this bundle.

The installer:
- backs up `main.py` and `globals.css`;
- copies new production modules and tests;
- installs Alembic revision `0004`;
- adds the production router to FastAPI once;
- adds the production-safety frontend page;
- adds `cryptography` to backend requirements;
- appends new environment-variable examples.

It does not run migrations, commit, or push automatically.

## Environment variables — set as Render Secrets

Generate a new key locally:
```powershell
Set-Location "$Root\backend"
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```
Use the first output for `TRADF_CREDENTIAL_ENCRYPTION_KEY` and the second for `TRADF_ADMIN_CONTROL_TOKEN`. Store both as Render Secrets. Keep secure offline recovery copies; never commit them.

Set these in both the API service and Background Worker where applicable:

| Variable | Initial value | Meaning |
|---|---|---|
| `TRADF_CREDENTIAL_ENCRYPTION_KEY` | generated Fernet key | Persistent encryption key; keep stable and backed up securely |
| `TRADF_ADMIN_CONTROL_TOKEN` | generated random token | Protects global kill-switch administration |
| `TRADF_GLOBAL_KILL_SWITCH` | `true` | Environment override; leave enabled during initial deployment |
| `TRADF_TESTNET_TRADING_ENABLED` | `false` | Testnet order endpoint disabled until explicitly enabled |
| `TRADF_WORKER_POLL_SECONDS` | `5` | Background worker polling interval |
| `LIVE_TRADING_ENABLED` | `false` | Must remain false |

Never put real secrets in `.env.example`, GitHub source, frontend variables, or logs. The encryption key must be identical on the API and worker services. Losing it makes stored API credentials undecryptable. Rotation requires a planned decrypt/re-encrypt migration; do not simply replace it.

## Migration

From backend:
```powershell
Set-Location "$Root\backend"
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

Expected revision:
`0004_tradf_production_infrastructure`

Do not run migration against a database until you have a current Neon backup/restore point.

## Test

```powershell
Set-Location "$Root\backend"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest tests\test_production_infrastructure.py -q
```

Then:
```powershell
Set-Location "$Root\frontend"
npm run build
```

## Render services

### API Web Service
- Root directory: `backend`
- Existing Dockerfile/API start command
- Set the environment variables above.
- Keep `TRADF_GLOBAL_KILL_SWITCH=true` and `TRADF_TESTNET_TRADING_ENABLED=false` for first deploy.
- The API container runs the existing Alembic migration command at startup; confirm logs and `/health/ready`.

### Background Worker
Create a separate Render Background Worker from the same repository:
- Root directory: `backend`
- Build: install dependencies as in the backend Dockerfile (or use the same Docker image)
- Start command: `python -m app.production_worker`
- Same `DATABASE_URL`, `TRADF_CREDENTIAL_ENCRYPTION_KEY`, and `TRADF_WORKER_POLL_SECONDS`
- Do not expose a public HTTP port.
- Keep it on the same release/commit as the API.

The worker uses database row locks and expiring leases. A second worker can safely compete for jobs; only one worker claims a due job at a time.

## API routes

Prefix: `/api/v1/v11/production`

- `GET /status`
- `POST /exchange/testnet/credentials`
- `GET /exchange/testnet/credentials?portfolio_id=...`
- `DELETE /exchange/testnet/credentials/{credential_id}`
- `POST /exchange/testnet/orders`
- `GET /exchange/testnet/orders?portfolio_id=...`
- `POST /exchange/testnet/orders/{order_id}/cancel`
- `GET /kill-switch`
- `POST /kill-switch/activate?reason=...`
- `POST /kill-switch/resume` with `{"confirm_resume":true}`
- `POST /kill-switch/global/activate` with `X-TRADF-ADMIN-TOKEN`
- `POST /kill-switch/global/resume` with `X-TRADF-ADMIN-TOKEN` and `{"confirm_resume":true}`
- `POST /scheduler/paper-burnin/start`
- `POST /scheduler/paper-burnin/stop?portfolio_id=...`
- `GET /scheduler/paper-burnin/status?portfolio_id=...`
- `GET /security/audit-snapshot`

All routes require the existing Bearer login token except public endpoints are intentionally absent.

## Testnet enablement sequence

1. Deploy with both kill controls on and order placement off.
2. Confirm migration and `/health/ready`.
3. Create Binance Spot Testnet API credentials; do not use a production key.
4. Set `TRADF_CREDENTIAL_ENCRYPTION_KEY` in Render before storing credentials.
5. Verify account permission response and confirm withdrawals are disabled at the exchange.
6. Only when ready to place a test order, set `TRADF_GLOBAL_KILL_SWITCH=false` and `TRADF_TESTNET_TRADING_ENABLED=true`.
7. Explicitly resume the user's kill switch using the API.
8. Submit a tiny limit order on Testnet, verify it appears in the Testnet account, and cancel it.
9. Activate the kill switch and verify outstanding test orders are cancelled.
10. Start the 21-day paper burn-in and ensure the Background Worker remains healthy.
11. Do not change `LIVE_TRADING_ENABLED=false`.

## Independent security review handoff

A third-party reviewer should receive:
- architecture and data-flow diagram;
- threat model for account takeover, credential theft, tenant crossover, replay, SSRF, scheduler abuse and exchange API misuse;
- source commit hash and CI scan results;
- database schema and migration;
- evidence that Testnet API keys have withdrawals disabled;
- key generation, storage, backup, rotation and incident-revocation procedures;
- kill-switch exercise evidence including cancellation failures;
- tenant-isolation test results;
- worker restart/lease-recovery test results;
- dependency and container scan results;
- manual penetration-test report and remediation retest.

The application cannot certify itself as independently audited. Obtain an external penetration test and remediation sign-off before considering any live-capital feature.


## Testnet smoke test (PowerShell)

Only use API keys generated by Binance Spot Test Network. Never paste production exchange credentials into TRADF.

```powershell
$Base = "https://smartmoney-platform.onrender.com"
$Token = Read-Host "TRADF bearer token"
$PortfolioId = Read-Host "Portfolio ID"
$Headers = @{ Authorization = "Bearer $Token" }

Invoke-RestMethod "$Base/api/v1/v11/production/status" -Headers $Headers
Invoke-RestMethod "$Base/api/v1/v11/production/kill-switch" -Headers $Headers

$ApiKey = Read-Host "Binance Spot Testnet API Key"
$ApiSecretSecure = Read-Host "Binance Spot Testnet API Secret" -AsSecureString
$ApiSecret = [System.Net.NetworkCredential]::new("",$ApiSecretSecure).Password
$Body = @{
  portfolio_id = $PortfolioId
  label = "Binance Spot Testnet"
  api_key = $ApiKey
  api_secret = $ApiSecret
  acknowledge_testnet_only = $true
} | ConvertTo-Json
$Credential = Invoke-RestMethod "$Base/api/v1/v11/production/exchange/testnet/credentials" `
  -Method Post -Headers $Headers -ContentType "application/json" -Body $Body
$ApiSecret = $null
$Body = $null
$Credential
```

PowerShell command history and process memory are sensitive. Do not save keys in scripts or transcripts. Prefer a dedicated secret manager for operational use.

Before any Testnet order:
1. Verify this is a Binance Spot Testnet account.
2. Verify the API reports `canTrade=true` and `canWithdraw=false`.
3. Set `TRADF_GLOBAL_KILL_SWITCH=false` and `TRADF_TESTNET_TRADING_ENABLED=true` only after reviewing deployment.
4. Use the global admin endpoint to resume the global DB switch.
5. Explicitly resume the individual user's switch.
6. Place only a tiny LIMIT order and cancel it.
7. Re-activate global and user kill switches and confirm cancellation in the exchange Testnet UI.

A missing encryption key, missing switch record, absent worker, or unverifiable exchange permissions must keep the relevant operation blocked.


### Place and cancel one tiny Testnet LIMIT order

After the global and user switches have been explicitly resumed, use a valid symbol/price/quantity for your Testnet account. Do not copy values blindly; exchange lot-size and tick-size filters apply.

```powershell
$OrderBody = @{
  credential_id = $Credential.id
  portfolio_id = $PortfolioId
  symbol = "BTCUSDT"
  side = "BUY"
  quantity = "0.00001"
  price = "10000"
  client_request_id = [guid]::NewGuid().ToString()
  confirm_testnet_only = $true
} | ConvertTo-Json

$Order = Invoke-RestMethod "$Base/api/v1/v11/production/exchange/testnet/orders" `
  -Method Post -Headers $Headers -ContentType "application/json" -Body $OrderBody

# Cancel immediately after confirming the order exists.
Invoke-RestMethod "$Base/api/v1/v11/production/exchange/testnet/orders/$($Order.id)/cancel" `
  -Method Post -Headers $Headers
```

The values above are illustrative only and may fail exchange precision/min-notional filters. Check Binance Testnet `exchangeInfo` before choosing a test order. The kill switch cancels outstanding orders; it does not liquidate already-filled assets.
