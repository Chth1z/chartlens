[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot

function Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "===== $Title ====="
}

function Run-Check {
    param([string]$Label, [scriptblock]$Command)
    Write-Host ""
    Write-Host "[$Label]"
    try {
        & $Command
    } catch {
        Write-Host $_.Exception.Message
    }
}

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $key, $value = $line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), "Process")
    }
}

Set-Location $Root
Import-DotEnv ".env"

Section "System"
Run-Check "PowerShell" { $PSVersionTable.PSVersion.ToString() }
Run-Check "python --version" { python --version }
Run-Check "node --version" { node --version }
Run-Check "npm --version" { npm --version }

Section "Project files"
Run-Check ".env" { if (Test-Path ".env") { "OK: .env exists" } else { "Missing: .env. Run install.cmd first." } }
Run-Check ".venv" { if (Test-Path ".\.venv\Scripts\python.exe") { & ".\.venv\Scripts\python.exe" --version } else { "Missing: .venv. Run install.cmd first." } }
Run-Check "frontend node_modules" { if (Test-Path ".\frontend\node_modules") { "OK: frontend dependencies installed" } else { "Missing: frontend\node_modules. Run install.cmd first." } }

Section "OCR dependencies"
Run-Check "pypdfium2" { & ".\.venv\Scripts\python.exe" -c "import pypdfium2; print('OK: pypdfium2')" }
Run-Check "RapidOCR" { & ".\.venv\Scripts\python.exe" -c "import rapidocr_onnxruntime; print('OK: rapidocr_onnxruntime')" }

Section "OAuth"
Run-Check "OAuth config" {
    if ($env:CHARTLENS_OAUTH_ENABLED -ne "true") {
        "OAuth disabled. Local mode is active."
        return
    }
    if ($env:CHARTLENS_OAUTH_PROVIDER -eq "chatgpt" -or -not $env:CHARTLENS_OAUTH_PROVIDER) {
        "OAuth enabled with built-in ChatGPT/Codex login. No manual client ID is required."
        "Callback URL: http://localhost:1455/auth/callback"
        return
    }
    $required = @(
        "CHARTLENS_OAUTH_CLIENT_ID",
        "CHARTLENS_OAUTH_AUTHORIZATION_URL",
        "CHARTLENS_OAUTH_TOKEN_URL",
        "CHARTLENS_OAUTH_USERINFO_URL"
    )
    $missing = @()
    foreach ($name in $required) {
        if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
            $missing += $name
        }
    }
    if ($missing.Count -eq 0) {
        "OAuth enabled and required endpoints are configured."
    } else {
        "OAuth enabled but missing: $($missing -join ', ')"
        "Set these in .env, then run stop.cmd and start.cmd. For local mode set CHARTLENS_OAUTH_ENABLED=false."
    }
}

Section "Ports"
Run-Check "Port 8000" { Test-NetConnection -ComputerName 127.0.0.1 -Port 8000 | Select-Object ComputerName, RemotePort, TcpTestSucceeded | Format-List }
Run-Check "Port 5173" { Test-NetConnection -ComputerName 127.0.0.1 -Port 5173 | Select-Object ComputerName, RemotePort, TcpTestSucceeded | Format-List }

Section "HTTP"
Run-Check "Backend health" { Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 3 | ConvertTo-Json }
Run-Check "Frontend" { (Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 3).StatusCode }

Section "Runtime pids"
Run-Check "backend.pid" { if (Test-Path ".\.runtime\backend.pid") { Get-Content ".\.runtime\backend.pid" } else { "No backend pid file" } }
Run-Check "frontend.pid" { if (Test-Path ".\.runtime\frontend.pid") { Get-Content ".\.runtime\frontend.pid" } else { "No frontend pid file" } }

Section "Logs"
Run-Check "backend.log" { if (Test-Path ".\logs\backend.log") { Get-Content ".\logs\backend.log" -Tail 80 } else { "No backend.log" } }
Run-Check "frontend.log" { if (Test-Path ".\logs\frontend.log") { Get-Content ".\logs\frontend.log" -Tail 80 } else { "No frontend.log" } }
