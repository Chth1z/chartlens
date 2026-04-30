$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location $root
$logDir = Join-Path $root "logs"
$frontendDir = Join-Path $root "frontend"
New-Item -ItemType Directory -Force $logDir | Out-Null
$python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
if (Test-Path ".\.venv-ocr\Scripts\python.exe") {
  & (Join-Path $root "scripts\start-ocr-sidecar.ps1")
}
Start-Process -WindowStyle Hidden -FilePath $python -ArgumentList "-m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000" -RedirectStandardOutput (Join-Path $logDir "backend.log") -RedirectStandardError (Join-Path $logDir "backend.err.log")
Start-Process -WindowStyle Hidden -FilePath "npm.cmd" -WorkingDirectory $frontendDir -ArgumentList "run dev -- --host 127.0.0.1" -RedirectStandardOutput (Join-Path $logDir "frontend.log") -RedirectStandardError (Join-Path $logDir "frontend.err.log")
Write-Host "EYEX backend: http://127.0.0.1:8000"
Write-Host "EYEX frontend: http://localhost:5173"
