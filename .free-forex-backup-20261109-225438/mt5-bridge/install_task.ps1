param(
    [string]$TaskName = "TRADF-MT5-Demo-Bridge"
)
$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "run_bridge.ps1"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "TRADF read-only MetaTrader 5 demo market data bridge" -Force
Write-Host "Scheduled task registered. It starts at user logon and restarts on failure." -ForegroundColor Green
