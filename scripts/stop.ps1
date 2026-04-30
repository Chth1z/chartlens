$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
$ports = @(8000, 5173, 8765)

function Test-EyexProcess {
  param([int]$ProcessId)

  $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  if ($null -eq $processInfo -or [string]::IsNullOrWhiteSpace($processInfo.CommandLine)) {
    return $false
  }

  $commandLine = $processInfo.CommandLine.ToLowerInvariant()
  $rootToken = $root.ToLowerInvariant()
  return $commandLine.Contains($rootToken) -or
    ($commandLine.Contains("uvicorn") -and $commandLine.Contains("app.main:app") -and $commandLine.Contains("--app-dir backend")) -or
    ($commandLine.Contains("vite") -and $commandLine.Contains("5173")) -or
    ($commandLine.Contains("ocr_sidecar.main:app") -and $commandLine.Contains("--app-dir backend"))
}

$stopped = 0
foreach ($port in $ports) {
  $ownerPids = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -gt 0 } |
    Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($ownerPid in $ownerPids) {
    if (Test-EyexProcess -ProcessId $ownerPid) {
      Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
      $stopped += 1
    } else {
      Write-Host "Skipped non-EYEX process $ownerPid on port $port."
    }
  }
}

Write-Host "Stopped $stopped EYEX process(es) on ports 8000, 5173 and 8765."
