[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $Root ".runtime"

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

function Find-ProjectPortProcess {
    param([ValidateSet("backend", "frontend")][string]$Name, [int]$Port)
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)" -ErrorAction SilentlyContinue
        if ($process -and (Test-ProjectCommand -CommandLine $process.CommandLine -Name $Name)) {
            $process
        }
    }
}

function Stop-ProcessId {
    param([int]$ProcessId, [string]$Label)
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $ProcessId -Force
        Write-Host "${Label}: stopped PID $ProcessId"
    }
}

function Stop-FromPidFile {
    param([string]$Name)
    $Path = Join-Path $RuntimeDir "$Name.pid"
    if (-not (Test-Path $Path)) {
        Write-Host "${Name}: no pid file"
        return
    }
    $PidValue = (Get-Content $Path -Raw).Trim()
    if (-not $PidValue) {
        Write-Host "${Name}: empty pid file"
        Remove-Item -LiteralPath $Path -Force
        return
    }
    Stop-ProcessId -ProcessId ([int]$PidValue) -Label $Name
    Remove-Item -LiteralPath $Path -Force
}

function Stop-ProjectProcesses {
    param([ValidateSet("backend", "frontend")][string]$Name, [int]$Port)
    $processes = @()
    $processes += Find-ProjectProcess -Name $Name
    $processes += Find-ProjectPortProcess -Name $Name -Port $Port
    $ids = $processes |
        Where-Object { $_ -and $_.ProcessId } |
        Select-Object -ExpandProperty ProcessId -Unique |
        Sort-Object -Descending
    if (-not $ids) {
        Write-Host "${Name}: no matching project process"
        return
    }
    foreach ($id in $ids) {
        Stop-ProcessId -ProcessId ([int]$id) -Label $Name
    }
}

Stop-FromPidFile "backend"
Stop-FromPidFile "frontend"
Stop-ProjectProcesses -Name "backend" -Port 8000
Stop-ProjectProcesses -Name "frontend" -Port 5173
Remove-Item -LiteralPath (Join-Path $RuntimeDir "start.lock") -Force -ErrorAction SilentlyContinue
