[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $Root ".runtime"
$LogDir = Join-Path $Root "logs"

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

function Wait-Http {
    param([string]$Url, [int]$Seconds)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
            return $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function Show-LogTail {
    param([string]$Path, [string]$Title)
    Write-Host ""
    Write-Host "===== $Title ($Path) ====="
    if (Test-Path $Path) {
        Get-Content $Path -Tail 80
    } else {
        Write-Host "Log file does not exist yet."
    }
}

function Test-ProjectCommand {
    param([string]$CommandLine, [string]$Name)
    if (-not $CommandLine) { return $false }
    $cmd = $CommandLine.ToLowerInvariant()
    $rootBackslash = $Root.ToLowerInvariant()
    $rootSlash = $rootBackslash.Replace("\", "/")
    $inProject = $cmd.Contains($rootBackslash) -or $cmd.Contains($rootSlash)
    if (-not $inProject) { return $false }
    if ($Name -eq "backend") {
        return $cmd.Contains("uvicorn") -and $cmd.Contains("app.main:app")
    }
    if ($Name -eq "frontend") {
        return $cmd.Contains("frontend") -and ($cmd.Contains("npm run dev") -or $cmd.Contains("vite"))
    }
    return $false
}

function Find-ProjectProcess {
    param([ValidateSet("backend", "frontend")][string]$Name)
    Get-CimInstance Win32_Process |
        Where-Object { Test-ProjectCommand -CommandLine $_.CommandLine -Name $Name } |
        Sort-Object ProcessId
}

function Test-PortListening {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    return $null -ne $connection
}

Set-Location $Root
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Missing .venv. Run install.cmd first."
}
if (-not (Test-Path ".\frontend\node_modules")) {
    throw "Missing frontend node_modules. Run install.cmd first."
}

New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir, ".\storage" | Out-Null

$LockPath = Join-Path $RuntimeDir "start.lock"
if (Test-Path $LockPath) {
    $lockAge = (Get-Date) - (Get-Item $LockPath).LastWriteTime
    if ($lockAge.TotalMinutes -lt 5) {
        throw "Another start.cmd is already running. Wait a moment, or run diagnose.cmd."
    }
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}

$LockStream = $null
try {
    $LockStream = [System.IO.File]::Open(
        $LockPath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )

    Import-DotEnv (Join-Path $Root ".env")

    $PwshCommand = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($PwshCommand) {
        $Shell = $PwshCommand.Source
    } else {
        $Shell = (Get-Command powershell -ErrorAction Stop).Source
    }

    $BackendLog = Join-Path $LogDir "backend.log"
    $FrontendLog = Join-Path $LogDir "frontend.log"
    $BackendCommand = "Set-Location '$Root'; & '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 *> '$BackendLog'"
    $FrontendCommand = "Set-Location '$Root\frontend'; npm run dev *> '$FrontendLog'"

    $BackendProcess = Find-ProjectProcess "backend" | Select-Object -First 1
    $FrontendProcess = Find-ProjectProcess "frontend" | Select-Object -First 1
    $ExistingBackendOk = Wait-Http "http://127.0.0.1:8000/api/health" 2
    $ExistingFrontendOk = Wait-Http "http://127.0.0.1:5173" 2

    $Backend = $null
    $Frontend = $null
    if ($ExistingBackendOk) {
        Write-Host "Backend already responds on http://127.0.0.1:8000"
        if ($BackendProcess) {
            Set-Content -Path (Join-Path $RuntimeDir "backend.pid") -Value $BackendProcess.ProcessId
        }
    } elseif ($BackendProcess) {
        throw "Backend project process already exists but is not healthy. Run stop.cmd, then start.cmd."
    } elseif (Test-PortListening 8000) {
        throw "Port 8000 is already in use by another process. Close it or change the backend port."
    } else {
        $Backend = Start-Process -FilePath $Shell -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $BackendCommand) -WindowStyle Hidden -PassThru
        Set-Content -Path (Join-Path $RuntimeDir "backend.pid") -Value $Backend.Id
    }

    if ($ExistingFrontendOk) {
        Write-Host "Frontend already responds on http://127.0.0.1:5173"
        if ($FrontendProcess) {
            Set-Content -Path (Join-Path $RuntimeDir "frontend.pid") -Value $FrontendProcess.ProcessId
        }
    } elseif ($FrontendProcess) {
        throw "Frontend project process already exists but is not healthy. Run stop.cmd, then start.cmd."
    } elseif (Test-PortListening 5173) {
        throw "Port 5173 is already in use by another process. Close it or change the frontend port."
    } else {
        $Frontend = Start-Process -FilePath $Shell -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $FrontendCommand) -WindowStyle Hidden -PassThru
        Set-Content -Path (Join-Path $RuntimeDir "frontend.pid") -Value $Frontend.Id
    }

    $BackendOk = Wait-Http "http://127.0.0.1:8000/api/health" 20
    $FrontendOk = Wait-Http "http://127.0.0.1:5173" 20

    if ($Backend) {
        Write-Host "Backend PID:  $($Backend.Id)  log: $BackendLog"
    } elseif ($BackendProcess) {
        Write-Host "Backend PID:  $($BackendProcess.ProcessId)  log: $BackendLog"
    } else {
        Write-Host "Backend PID:  existing process  log: $BackendLog"
    }
    if ($Frontend) {
        Write-Host "Frontend PID: $($Frontend.Id) log: $FrontendLog"
    } elseif ($FrontendProcess) {
        Write-Host "Frontend PID: $($FrontendProcess.ProcessId) log: $FrontendLog"
    } else {
        Write-Host "Frontend PID: existing process log: $FrontendLog"
    }
    Write-Host "Backend:  http://127.0.0.1:8000  ready=$BackendOk"
    Write-Host "Frontend: http://127.0.0.1:5173  ready=$FrontendOk"
    if (-not ($BackendOk -and $FrontendOk)) {
        Show-LogTail $BackendLog "backend.log"
        Show-LogTail $FrontendLog "frontend.log"
        throw "Service startup failed. Review the log output above, or run diagnose.cmd."
    }

    Write-Host "Open http://127.0.0.1:5173"
    Write-Host "Use stop.cmd to stop services started by this script."
} finally {
    if ($LockStream) {
        $LockStream.Dispose()
    }
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}
