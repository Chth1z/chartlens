[CmdletBinding()]
param(
  [string]$OcrPython = ".\.venv-ocr\Scripts\python.exe",
  [ValidateSet("Auto", "Require", "Off")]
  [string]$GpuPolicy = "Auto",
  [string]$DirectMLModelDir = "",
  [string]$RemoteRocmSidecarUrl = "",
  [switch]$DisableAutoDirectMLModelInstall
)

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location $root
. (Join-Path $scriptDir "ocr-gpu-routing.ps1")

function Test-CommandAvailable {
  param([string]$Name)
  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if ($command) {
    return @{ available = $true; path = $command.Source }
  }
  return @{ available = $false; path = "" }
}

function Invoke-PythonProbe {
  param([string]$PythonExe)
  if (!(Test-Path $PythonExe)) {
    return @{ available = $false; error = "Python not found: $PythonExe" }
  }
  $code = @"
import importlib.util, json
payload = {}
try:
    import paddle
    rocm = getattr(paddle, "is_compiled_with_rocm", None)
    payload["paddle"] = {
        "available": True,
        "version": getattr(paddle, "__version__", ""),
        "current": str(paddle.get_device()),
        "compiled_cuda": bool(paddle.is_compiled_with_cuda()),
        "compiled_rocm": bool(rocm()) if callable(rocm) else False,
    }
except Exception as exc:
    payload["paddle"] = {"available": False, "error": str(exc)}
try:
    import onnxruntime as ort
    payload["onnxruntime"] = {"available": True, "providers": list(ort.get_available_providers())}
except Exception as exc:
    payload["onnxruntime"] = {"available": False, "error": str(exc)}
payload["packages"] = {
    "paddleocr": importlib.util.find_spec("paddleocr") is not None,
    "rapidocr": importlib.util.find_spec("rapidocr") is not None,
}
print(json.dumps(payload, ensure_ascii=False))
"@
  try {
    $output = $code | & $PythonExe - 2>$null
    if (!$output) {
      return @{ available = $false; error = "Python probe returned no output" }
    }
    return ($output -join "`n") | ConvertFrom-Json
  } catch {
    return @{ available = $false; error = $_.Exception.Message }
  }
}

$gpus = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Select-Object Name, AdapterCompatibility, DriverVersion, AdapterRAM)
$pythonProbe = Invoke-PythonProbe -PythonExe $OcrPython
$docker = Test-CommandAvailable "docker"
$wsl = Test-CommandAvailable "wsl"
$nvidiaSmi = Test-CommandAvailable "nvidia-smi"
$rocminfo = Test-CommandAvailable "rocminfo"
$rocmSmi = Test-CommandAvailable "rocm-smi"
$hipcc = Test-CommandAvailable "hipcc"

$hasDirectML = $false
if ($pythonProbe.onnxruntime -and $pythonProbe.onnxruntime.providers) {
  $hasDirectML = @($pythonProbe.onnxruntime.providers) -contains "DmlExecutionProvider"
}

$hasRadeon = @($gpus | Where-Object { $_.Name -match "AMD|Radeon" }).Count -gt 0
$route = Resolve-EyexOcrGpuRoute -ProjectRoot $root -GpuPolicy $GpuPolicy -DirectMLModelDir $DirectMLModelDir -RemoteRocmSidecarUrl "" -DisableAutoDirectMLModelInstall:$DisableAutoDirectMLModelInstall
$recommendation = $route.ocr_profile

[ordered]@{
  gpu = $gpus
  commands = @{
    "nvidia-smi" = $nvidiaSmi
    docker = $docker
    wsl = $wsl
    rocminfo = $rocminfo
    "rocm-smi" = $rocmSmi
    hipcc = $hipcc
  }
  python = $pythonProbe
  directml = @{
    available = $hasDirectML
    model_dir_ready = Test-EyexDirectMLModelDir -Path $route.directml_model_dir
    model_dir = $route.directml_model_dir
    note = "Requires ONNX Runtime DirectML and an EYEX project-local PP-OCRv5 ONNX model directory."
  }
  rocm = @{
    local_ready = [bool]($pythonProbe.paddle -and $pythonProbe.paddle.compiled_rocm)
    rx6600_default_enabled = $false
    note = "ROCm/PaddleOCR-VL is parked outside the default EYEX OCR route."
  }
  paddleocr_vl = @{
    enabled = $false
    status = "disabled"
    reason = "PaddleOCR-VL is temporarily disabled in EYEX; the default route is local PP-OCRv5 DirectML plus PP-StructureV3 when available."
  }
  gpu_route = $route
  recommended_ocr_profile = $recommendation
} | ConvertTo-Json -Depth 8
