[CmdletBinding()]
param(
  [string]$ProfileId = "",
  [string]$PythonExe = "",
  [double]$Timeout = 20.0
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
$runner = Join-Path $root "scripts\check-llm-connectivity.py"
$defaultBackendPython = Join-Path $root ".venv\Scripts\python.exe"
$resolvedPython = if ($PythonExe.Trim()) {
  $PythonExe
} elseif (Test-Path $defaultBackendPython) {
  $defaultBackendPython
} else {
  "python"
}

$cliArgs = @()
if ($ProfileId.Trim()) {
  $cliArgs += @("--profile-id", $ProfileId)
}
$cliArgs += @("--timeout", $Timeout.ToString())

& $resolvedPython $runner @cliArgs
$exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
exit $exitCode
