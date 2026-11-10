param(
    [int]$Days = 90,
    [string]$ProjectRoot = "Q:\programing\website\New-bot\smartmoney-platform"
)

$ErrorActionPreference = "Stop"

$Backend = Join-Path $ProjectRoot "backend"
$DataRoot = Join-Path $Backend "data\forex"
$RawRoot = Join-Path $DataRoot "raw"
New-Item -ItemType Directory -Force -Path $RawRoot | Out-Null

$Symbols = @("EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD","XAUUSD")
$StartDate = (Get-Date).ToUniversalTime().AddDays(-$Days).ToString("yyyy-MM-dd")
$EndDate = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")

Write-Host "Dukascopy historical M1 download" -ForegroundColor Cyan
Write-Host "Range UTC: $StartDate to $EndDate"
Write-Host "Symbols: $($Symbols -join ', ')"

Push-Location $RawRoot
try {
    foreach ($Symbol in $Symbols) {
        $Instrument = $Symbol.ToLowerInvariant()
        Write-Host "`nDownloading $Symbol M1..." -ForegroundColor Yellow

        & npx --yes dukascopy-node -i $Instrument -from $StartDate -to $EndDate -t m1 -f csv --cache
        if ($LASTEXITCODE -ne 0) {
            throw "Dukascopy download failed for $Symbol (exit $LASTEXITCODE)"
        }

        $Candidates = Get-ChildItem ".\download" -Recurse -File -Filter "$Instrument-m1-bid-*.csv" |
            Sort-Object LastWriteTime -Descending

        if (!$Candidates -or $Candidates.Count -eq 0) {
            throw "No M1 bid CSV found for $Symbol. Inspect $RawRoot\download"
        }

        Copy-Item $Candidates[0].FullName (Join-Path $DataRoot "$Symbol`_m1.csv") -Force
        Write-Host "Saved $Symbol`_m1.csv" -ForegroundColor Green
    }
}
finally {
    Pop-Location
}

$ExampleCosts = Join-Path $DataRoot "forex_costs.example.json"
$Costs = Join-Path $DataRoot "forex_costs.json"
if (!(Test-Path $Costs)) {
    Copy-Item $ExampleCosts $Costs
    Write-Host "Created forex_costs.json from example assumptions." -ForegroundColor Yellow
}

Write-Host "`nDOWNLOAD COMPLETE. Next: import history and run backtests from backend." -ForegroundColor Green
