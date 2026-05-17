[CmdletBinding()]
param(
  [string]$ProfileId = "mock_general",
  [string]$PythonExe = "",
  [string]$Output = "-",
  [switch]$AllowBlocked
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
$runner = Join-Path $root "scripts\run-extraction-eval.py"
$defaultBackendPython = Join-Path $root ".venv\Scripts\python.exe"
$resolvedPython = if ($PythonExe.Trim()) {
  $PythonExe
} elseif (Test-Path $defaultBackendPython) {
  $defaultBackendPython
} else {
  "python"
}

$cliArgs = @("--profile-id", $ProfileId, "--output", $Output)
if ($AllowBlocked) {
  $cliArgs += "--allow-blocked"
}

& $resolvedPython $runner @cliArgs
$exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
if ($exitCode -ne 0) {
  throw "Extraction evaluation run failed with exit code ${exitCode}."
}
