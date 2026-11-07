# V9 foundation patch — installation

1. Stop the running API with `CTRL+C`.
2. Extract this ZIP to a folder, for example `C:\Users\taha\Downloads\smartmoney-v9-foundation`.
3. Open PowerShell in the extracted folder.
4. Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\INSTALL_V9_FOUNDATION.ps1
```

5. The installer creates timestamped backups before replacing existing files.
6. Activate the existing backend virtual environment and run:

```powershell
cd "Q:\programing\website\New-bot\smartmoney-platform\backend"
.\.venv\Scripts\Activate.ps1
python -m compileall app
python -m pytest tests -v
```

7. Start the API again:

```powershell
uvicorn app.main:app --reload --port 8000
```

The patch does not change the frontend and does not include or overwrite `.env`, the SQLite journal database, `.venv`, `node_modules`, or user data.

## New API examples

Risk preflight:

```powershell
$body = @{
  balance = 10000
  equity = 10000
  day_start_equity = 10000
  week_start_equity = 10000
  month_start_equity = 10000
  peak_equity = 10000
  entry = 100
  stop = 98
  quantity = 10
  open_trades = @()
  counter_trend = $false
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/risk/preflight" `
  -Method POST -ContentType "application/json" -Body $body
```

Calibration report:

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/intelligence/calibration/report" |
  ConvertTo-Json -Depth 10
```

Backtest replay accepts candles plus signal events. A signal at candle index `i` can only enter at candle `i+1` open:

```powershell
$body = @{
  candles = @(
    @{time=0; open=100; high=101; low=99; close=100},
    @{time=60; open=100; high=101; low=99; close=100},
    @{time=120; open=100; high=106; low=99; close=105}
  )
  signals = @(
    @{index=0; direction="bullish"; stop_loss=98; take_profit=105; quantity=1}
  )
  initial_equity = 10000
  spread = 0
  slippage = 0
  commission_pct = 0
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/backtest/replay" `
  -Method POST -ContentType "application/json" -Body $body |
  ConvertTo-Json -Depth 10
```
