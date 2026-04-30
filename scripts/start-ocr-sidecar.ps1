[CmdletBinding()]
param(
  [string]$VenvPath = ".venv-ocr",
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8765,
  [string]$PaddleModelSource = "BOS",
  [string]$SidecarEngines = "",
  [ValidateSet("auto", "cpu", "gpu", "cuda", "rocm", "directml", "remote")]
  [string]$OcrDevice = "auto",
  [ValidateSet("auto", "cpu", "cuda", "rocm", "directml", "remote")]
  [string]$OcrAccelerator = "auto"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
$logDir = Join-Path $root "logs"
$venvPython = Join-Path (Join-Path $root $VenvPath) "Scripts\python.exe"

function Import-DotEnv {
  param([string]$Path)
  if (!(Test-Path $Path)) {
    return
  }
  foreach ($line in Get-Content -LiteralPath $Path) {
    $trimmed = $line.Trim()
    if (!$trimmed -or $trimmed.StartsWith("#") -or !$trimmed.Contains("=")) {
      continue
    }
    $parts = $trimmed.Split("=", 2)
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    Set-Item -Path "Env:$name" -Value $value
  }
}

function Set-OcrProjectRuntimeRoots {
  param([string]$Root)
  $cacheRoot = Join-Path $Root "var\cache\ocr-runtime"
  $tmpRoot = Join-Path $cacheRoot "tmp"
  $modelRoot = Join-Path $Root "var\models"
  foreach ($path in @($cacheRoot, $tmpRoot, $modelRoot)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
  }
  if (!$env:EYEX_OCR_MODEL_ROOT) { $env:EYEX_OCR_MODEL_ROOT = $modelRoot }
  if (!$env:HF_HOME) { $env:HF_HOME = Join-Path $cacheRoot "huggingface" }
  if (!$env:HUGGINGFACE_HUB_CACHE) { $env:HUGGINGFACE_HUB_CACHE = Join-Path $env:HF_HOME "hub" }
  if (!$env:PADDLE_HOME) { $env:PADDLE_HOME = Join-Path $cacheRoot "paddle" }
  if (!$env:PADDLEOCR_HOME) { $env:PADDLEOCR_HOME = Join-Path $cacheRoot "paddleocr" }
  if (!$env:PADDLEX_HOME) { $env:PADDLEX_HOME = Join-Path $cacheRoot "paddlex" }
  if (!$env:PADDLE_PDX_CACHE_HOME) { $env:PADDLE_PDX_CACHE_HOME = $env:PADDLEX_HOME }
  if (!$env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME = Join-Path $cacheRoot "xdg" }
  if (!$env:TORCH_HOME) { $env:TORCH_HOME = Join-Path $cacheRoot "torch" }
  $env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
  $env:TEMP = $tmpRoot
  $env:TMP = $tmpRoot
}

if (!(Test-Path $venvPython)) {
  throw "OCR sidecar venv not found at $venvPython. Run scripts\install-intelligent-ocr.ps1 first."
}

Import-DotEnv (Join-Path $root ".env")
Set-OcrProjectRuntimeRoots -Root $root
if (!$PSBoundParameters.ContainsKey("PaddleModelSource") -and $env:PADDLE_PDX_MODEL_SOURCE) {
  $PaddleModelSource = $env:PADDLE_PDX_MODEL_SOURCE
}
if (!$PSBoundParameters.ContainsKey("SidecarEngines") -and $env:EYEX_OCR_SIDECAR_ENGINES) {
  $SidecarEngines = $env:EYEX_OCR_SIDECAR_ENGINES
}
if (!$PSBoundParameters.ContainsKey("OcrDevice") -and $env:EYEX_OCR_DEVICE) {
  $OcrDevice = $env:EYEX_OCR_DEVICE
}
if (!$PSBoundParameters.ContainsKey("OcrAccelerator") -and $env:EYEX_OCR_ACCELERATOR) {
  $OcrAccelerator = $env:EYEX_OCR_ACCELERATOR
}

New-Item -ItemType Directory -Force $logDir | Out-Null
$env:PADDLE_PDX_MODEL_SOURCE = $PaddleModelSource
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
$env:DISABLE_MODEL_SOURCE_CHECK = "True"
$env:EYEX_OCR_SIDECAR_ENGINES = $SidecarEngines
$env:EYEX_OCR_DEVICE = $OcrDevice
$env:EYEX_OCR_ACCELERATOR = $OcrAccelerator
$existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
  Write-Host "OCR sidecar port $Port is already in use by process $($existing.OwningProcess)."
  Write-Host "Health: http://$HostName`:$Port/health"
  exit 0
}

Start-Process `
  -WindowStyle Hidden `
  -FilePath $venvPython `
  -ArgumentList "-m uvicorn ocr_sidecar.main:app --app-dir backend --host $HostName --port $Port" `
  -WorkingDirectory $root `
  -RedirectStandardOutput (Join-Path $logDir "ocr-sidecar.log") `
  -RedirectStandardError (Join-Path $logDir "ocr-sidecar.err.log")

Write-Host "EYEX OCR sidecar: http://$HostName`:$Port"
Write-Host "Health: http://$HostName`:$Port/health"
Write-Host "OCR device: $OcrDevice"
Write-Host "OCR accelerator: $OcrAccelerator"
Write-Host "OCR sidecar engines: $SidecarEngines"
