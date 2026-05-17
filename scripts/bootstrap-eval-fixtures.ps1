[CmdletBinding()]
param(
  [string]$ProfileId = "mock_general",
  [string]$PythonExe = "",
  [ValidateSet("rule", "llm")]
  [string]$Provider = "rule",
  [switch]$Baseline,
  [switch]$CleanOnly,
  [switch]$UnsafeEvalAllowRemoteContext
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
$runner = Join-Path $root "scripts\bootstrap-eval-fixtures.py"
$defaultBackendPython = Join-Path $root ".venv\Scripts\python.exe"
$resolvedPython = if ($PythonExe.Trim()) {
  $PythonExe
} elseif (Test-Path $defaultBackendPython) {
  $defaultBackendPython
} else {
  "python"
}

$cliArgs = @("--profile-id", $ProfileId, "--provider", $Provider)
if ($Baseline) {
  $cliArgs += "--baseline"
}
if ($CleanOnly) {
  $cliArgs += "--clean-only"
}
if ($UnsafeEvalAllowRemoteContext) {
  $cliArgs += "--unsafe-eval-allow-remote-context"
}

& $resolvedPython $runner @cliArgs
$exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
if ($exitCode -ne 0) {
  throw "bootstrap-eval-fixtures failed with exit code ${exitCode}."
}
