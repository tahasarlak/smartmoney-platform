$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (!(Test-Path ".\.venv\Scripts\python.exe")) {
    py -3.12 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (!(Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env. Edit it with your Render URL and bridge token, then run this script again." -ForegroundColor Yellow
    exit 0
}

.\.venv\Scripts\python.exe .\bridge.py
