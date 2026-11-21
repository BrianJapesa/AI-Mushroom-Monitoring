$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$logs = Join-Path $root 'logs'
$outLog = Join-Path $logs 'prototype.out.log'
$errorLog = Join-Path $logs 'prototype.error.log'
$url = 'http://127.0.0.1:5000/'

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Python setup is missing. Run the setup steps in docs/PROTOTYPE.md first.' -ForegroundColor Yellow
    exit 1
}
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:5000/health' -TimeoutSec 2 | Out-Null
    Start-Process $url
    Write-Host 'The prototype is already running. Opening the dashboard.'
    exit 0
} catch { }

New-Item -ItemType Directory -Force -Path $logs | Out-Null
$process = Start-Process -FilePath $python -ArgumentList 'backend\app.py' -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errorLog
$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/health' -TimeoutSec 2
        if ($health.status -eq 'ok') { $ready = $true; break }
    } catch { }
}
if (-not $ready) {
    Write-Host 'The prototype did not start. Check logs/prototype.error.log, then run the setup steps in docs/PROTOTYPE.md.' -ForegroundColor Red
    exit 1
}
Start-Process $url
Write-Host 'Prototype started. Dashboard: http://127.0.0.1:5000/'
