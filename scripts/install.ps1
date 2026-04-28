[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Require-Command {
    param([string]$Name, [string]$InstallHint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $InstallHint"
    }
}

Set-Location $Root
Require-Command python "Install Python 3.12+ and ensure python is on PATH."
Require-Command node "Install Node.js 22+ and ensure node is on PATH."
Require-Command npm "Install Node.js/npm and ensure npm is on PATH."

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Edit it before enabling OpenAI or OAuth."
}

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r ".\backend\requirements-dev.txt"

Push-Location ".\frontend"
npm install
Pop-Location

New-Item -ItemType Directory -Force -Path ".\storage", ".\logs", ".\.runtime" | Out-Null

Write-Host ""
Write-Host "Install complete."
Write-Host "Run start.cmd, then open http://127.0.0.1:5173"
