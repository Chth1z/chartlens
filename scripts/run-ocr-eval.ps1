[CmdletBinding()]
param(
  [string]$ProfileId = "mock_general",
  [string]$PythonExe = "",
  [switch]$AllowEmptyHardwareProfile
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
$runner = Join-Path $root "scripts\run-ocr-eval.py"
$defaultOcrPython = Join-Path $root ".venv-ocr\Scripts\python.exe"
$resolvedPython = if ($PythonExe.Trim()) {
  $PythonExe
} elseif (Test-Path $defaultOcrPython) {
  $defaultOcrPython
} else {
  "python"
}

$args = @("--profile-id", $ProfileId)
if ($AllowEmptyHardwareProfile) {
  $args += "--allow-empty-hardware-profile"
}

& $resolvedPython $runner @args
$exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
if ($exitCode -ne 0) {
  throw "OCR regression run failed with exit code ${exitCode}."
}
