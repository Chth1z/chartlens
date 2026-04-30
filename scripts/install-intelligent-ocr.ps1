[CmdletBinding()]
param(
  [string]$PythonExe = "py",
  [string[]]$PythonArgs = @("-3.11"),
  [string]$VenvPath = ".venv-ocr",
  [int]$Port = 8765,
  [string]$PaddleIndexUrl = "",
  [string]$PaddleCpuPackage = "paddlepaddle==3.2.2",
  [string]$PaddleGpuPackage = "paddlepaddle-gpu==3.2.2",
  [string]$PaddleCpuIndexUrl = "https://www.paddlepaddle.org.cn/packages/stable/cpu/",
  [string]$PaddleGpuIndexUrl = "https://www.paddlepaddle.org.cn/packages/stable/cu126/",
  [string]$PaddleModelSource = "BOS",
  [switch]$SkipPaddleFramework,
  [switch]$SkipWarmup,
  [switch]$StartSidecar,
  [switch]$NoStartSidecar,
  [switch]$UseGpu,
  [switch]$ForceGpu,
  [switch]$UseDirectML,
  [ValidateSet("Auto", "Require", "Off")]
  [string]$GpuPolicy = "Require",
  [string]$DirectMLModelDir = "",
  [switch]$DisableAutoDirectMLModelInstall,
  [string]$RemoteRocmSidecarUrl = "",
  [switch]$UseDeepSeek,
  [string]$DeepSeekApiKey = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
$venv = Join-Path $root $VenvPath
$venvPython = Join-Path $venv "Scripts\python.exe"
$envPath = Join-Path $root ".env"
$envExamplePath = Join-Path $root ".env.example"
. (Join-Path $scriptDir "ocr-gpu-routing.ps1")

function Invoke-CheckedNative {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [string[]]$Arguments = @()
  )
  & $FilePath @Arguments
  $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
  if ($exitCode -ne 0) {
    throw "Command failed with exit code ${exitCode}: $FilePath $($Arguments -join ' ')"
  }
}

function Invoke-BasePython {
  param([string[]]$ExtraArgs)
  Invoke-CheckedNative -FilePath $PythonExe -Arguments (@($PythonArgs) + @($ExtraArgs))
}

function Invoke-GeneratedPythonScript {
  param(
    [string]$Python,
    [string]$ScriptPath,
    [string]$Content
  )
  $scriptDirForFile = Split-Path -Parent $ScriptPath
  New-Item -ItemType Directory -Force -Path $scriptDirForFile | Out-Null
  Set-Content -LiteralPath $ScriptPath -Value $Content -Encoding UTF8
  Invoke-CheckedNative -FilePath $Python -Arguments @($ScriptPath)
}

function Stop-EyexOcrSidecarOnPort {
  param(
    [int]$Port,
    [string]$VenvPython
  )
  $connections = @(Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess } | Select-Object -ExpandProperty OwningProcess -Unique)
  foreach ($processId in $connections) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    $commandLine = [string]$proc.CommandLine
    $executable = [string]$proc.ExecutablePath
    $isEyexSidecar = $commandLine -match "ocr_sidecar\.main:app"
    if (!$isEyexSidecar -and $executable -and (Test-Path $VenvPython)) {
      $isEyexSidecar = [System.IO.Path]::GetFullPath($executable).Equals([System.IO.Path]::GetFullPath($VenvPython), [System.StringComparison]::OrdinalIgnoreCase)
    }
    if (!$isEyexSidecar) {
      throw "OCR sidecar port $Port is already in use by non-EYEX process $processId. Stop that process or choose another port."
    }
    Write-Host "Stopping existing EYEX OCR sidecar on port $Port (process $processId) before installation."
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
  }
}

function Set-EnvValue {
  param(
    [string]$Path,
    [string]$Name,
    [string]$Value,
    [switch]$Overwrite
  )
  if (!(Test-Path $Path)) {
    if (Test-Path $envExamplePath) {
      Copy-Item -LiteralPath $envExamplePath -Destination $Path
    } else {
      New-Item -ItemType File -Path $Path | Out-Null
    }
  }
  $lines = @(Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)
  $pattern = "^$([regex]::Escape($Name))="
  $index = -1
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match $pattern) {
      $index = $i
      break
    }
  }
  if ($index -ge 0) {
    $current = $lines[$index]
    if ($Overwrite -or $current -eq "$Name=") {
      $lines[$index] = "$Name=$Value"
    }
  } else {
    $lines += "$Name=$Value"
  }
  Set-Content -LiteralPath $Path -Value $lines -Encoding UTF8
}

function Set-OcrProjectWriteRoots {
  param([string]$Root)
  $modelRoot = Join-Path $Root "var\models"
  $cacheRoot = Join-Path $Root "var\cache\ocr-install"
  $tmpRoot = Join-Path $cacheRoot "tmp"
  $hfRoot = Join-Path $cacheRoot "huggingface"
  $pipCache = Join-Path $cacheRoot "pip"
  $paddleRoot = Join-Path $cacheRoot "paddle"
  $paddleOcrRoot = Join-Path $cacheRoot "paddleocr"
  $paddlexRoot = Join-Path $cacheRoot "paddlex"
  foreach ($path in @($modelRoot, $cacheRoot, $tmpRoot, $hfRoot, $pipCache, $paddleRoot, $paddleOcrRoot, $paddlexRoot)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
  }
  $env:EYEX_OCR_MODEL_ROOT = $modelRoot
  $env:EYEX_OCR_INSTALL_CACHE_ROOT = $cacheRoot
  $env:HF_HOME = $hfRoot
  $env:HUGGINGFACE_HUB_CACHE = Join-Path $hfRoot "hub"
  $env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
  $env:PIP_CACHE_DIR = $pipCache
  $env:PADDLE_HOME = $paddleRoot
  $env:PADDLEOCR_HOME = $paddleOcrRoot
  $env:PADDLEX_HOME = $paddlexRoot
  $env:PADDLE_PDX_CACHE_HOME = $paddlexRoot
  $env:XDG_CACHE_HOME = Join-Path $cacheRoot "xdg"
  $env:TORCH_HOME = Join-Path $cacheRoot "torch"
  $env:TEMP = $tmpRoot
  $env:TMP = $tmpRoot
  return [pscustomobject]@{
    model_root = $modelRoot
    cache_root = $cacheRoot
    tmp_root = $tmpRoot
  }
}

function Ensure-EyexDirectMLModels {
  param(
    [string]$Python,
    [string]$ModelDir,
    [string]$CacheRoot,
    [switch]$DisableAutoInstall
  )
  if (Test-EyexDirectMLModelDir -Path $ModelDir) {
    Write-Host "DirectML PP-OCRv5 ONNX models already exist: $ModelDir"
    return
  }
  if ($DisableAutoInstall) {
    throw "DirectML PP-OCRv5 ONNX models are missing and automatic model installation is disabled: $ModelDir"
  }

  New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null
  Write-Host "Preparing PP-OCRv5 DirectML ONNX models under project directory: $ModelDir"
  Invoke-CheckedNative -FilePath $Python -Arguments @("-m", "pip", "install", "rapidocr>=3.0.0", "onnxruntime-directml")

  $env:EYEX_OCR_DIRECTML_MODEL_DIR = $ModelDir
  $env:EYEX_OCR_INSTALL_CACHE_ROOT = $CacheRoot
  $prepareDirectMLModels = @'
from pathlib import Path
import json
import os
import shutil

from rapidocr import OCRVersion, RapidOCR

model_dir = Path(os.environ["EYEX_OCR_DIRECTML_MODEL_DIR"]).resolve()
model_dir.mkdir(parents=True, exist_ok=True)

params = {
    "Global.model_root_dir": str(model_dir),
    "EngineConfig.onnxruntime.use_dml": True,
    "Det.ocr_version": OCRVersion.PPOCRV5,
    "Rec.ocr_version": OCRVersion.PPOCRV5,
}
engine = RapidOCR(params=params)

provider_map = {}
for name, component_name in {
    "det": "text_det",
    "cls": "text_cls",
    "rec": "text_rec",
}.items():
    component = getattr(engine, component_name, None)
    session_wrapper = getattr(component, "session", None)
    session = getattr(session_wrapper, "session", None)
    providers = session.get_providers() if session is not None else []
    provider_map[name] = providers
    if "DmlExecutionProvider" not in providers:
        raise SystemExit(f"{name} did not activate DmlExecutionProvider; active providers={providers}")

aliases = {
    "det.onnx": model_dir / "ch_PP-OCRv5_det_mobile.onnx",
    "rec.onnx": model_dir / "ch_PP-OCRv5_rec_mobile.onnx",
    "cls.onnx": model_dir / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
}
for alias, source in aliases.items():
    if source.exists():
        shutil.copy2(source, model_dir / alias)

manifest = {
    "source": "RapidAI/RapidOCR ModelScope ONNX artifacts",
    "ocr_version": "PP-OCRv5",
    "accelerator": "directml",
    "providers": provider_map,
    "det_model": str(model_dir / "ch_PP-OCRv5_det_mobile.onnx"),
    "rec_model": str(model_dir / "ch_PP-OCRv5_rec_mobile.onnx"),
    "cls_model": str(model_dir / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
    "aliases": {alias: str(path) for alias, path in aliases.items() if path.exists()},
}
(model_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print("Prepared DirectML PP-OCRv5 ONNX models:", model_dir)
'@
  Invoke-GeneratedPythonScript -Python $Python -ScriptPath (Join-Path $CacheRoot "tmp\prepare-directml-models.py") -Content $prepareDirectMLModels
}

Write-Host "Installing EYEX intelligent OCR sidecar under $venv"
$writeRoots = Set-OcrProjectWriteRoots -Root $root
$gpuRoute = Resolve-EyexOcrGpuRoute -ProjectRoot $root -GpuPolicy $GpuPolicy -DirectMLModelDir $DirectMLModelDir -RemoteRocmSidecarUrl $RemoteRocmSidecarUrl -DisableAutoDirectMLModelInstall:$DisableAutoDirectMLModelInstall
if ($UseGpu -and $gpuRoute.route -ne "nvidia_cuda") {
  throw "-UseGpu requests the NVIDIA/CUDA Paddle route, but detected route is '$($gpuRoute.route)'."
}
if ($UseDirectML -and $gpuRoute.route -notin @("amd_directml", "windows_directml")) {
  throw "-UseDirectML requests the ONNX Runtime DirectML route, but detected route is '$($gpuRoute.route)'."
}
Assert-EyexOcrGpuRoute -Route $gpuRoute -GpuPolicy $GpuPolicy
if ($GpuPolicy -eq "Auto" -and !$gpuRoute.can_guarantee_gpu) {
  Write-Warning "No guaranteed GPU OCR route is ready. Falling back to CPU because GpuPolicy=Auto. Use -GpuPolicy Require to fail instead."
  $gpuRoute = Resolve-EyexOcrGpuRoute -ProjectRoot $root -GpuPolicy Off
}
Write-Host "Detected OCR GPU route: $($gpuRoute.route)"
Write-Host "OCR GPU route reason: $($gpuRoute.reason)"

$shouldStartSidecar = !$NoStartSidecar
$routeUseGpu = [bool]$gpuRoute.use_gpu
$routeUseDirectML = [bool]$gpuRoute.use_directml
$env:PADDLE_PDX_MODEL_SOURCE = $PaddleModelSource
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
$env:DISABLE_MODEL_SOURCE_CHECK = "True"
$version = (Invoke-BasePython @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")).Trim()
$parts = $version.Split(".")
$major = [int]$parts[0]
$minor = [int]$parts[1]
if ($major -ne 3 -or $minor -lt 9 -or $minor -gt 13) {
  throw "PaddleOCR-VL sidecar requires Python 3.9-3.13. Current interpreter is Python $version. Pass -PythonExe/-PythonArgs for Python 3.11."
}

Stop-EyexOcrSidecarOnPort -Port $Port -VenvPython $venvPython
if (!(Test-Path $venvPython)) {
  Invoke-BasePython @("-m", "venv", $venv)
} else {
  Write-Host "OCR sidecar venv already exists: $venv"
}
Invoke-CheckedNative -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools<82", "wheel")

if (!$SkipPaddleFramework) {
  if ($routeUseGpu) {
    $hasNvidiaSmi = [bool](Get-Command "nvidia-smi" -ErrorAction SilentlyContinue)
    if (!$hasNvidiaSmi -and !$ForceGpu) {
      throw "PaddleOCR CUDA install requires NVIDIA nvidia-smi. For AMD Radeon, use -DirectMLModelDir with PP-OCRv5 ONNX files or -RemoteRocmSidecarUrl."
    }
  }
  $selectedPaddlePackage = if ($routeUseGpu) { $PaddleGpuPackage } else { $PaddleCpuPackage }
  $selectedPaddleIndexUrl = if ($PaddleIndexUrl.Trim()) { $PaddleIndexUrl } elseif ($routeUseGpu) { $PaddleGpuIndexUrl } else { $PaddleCpuIndexUrl }
  Invoke-CheckedNative -FilePath $venvPython -Arguments @("-m", "pip", "install", $selectedPaddlePackage, "-i", $selectedPaddleIndexUrl)
  if ($routeUseGpu) {
    Invoke-CheckedNative -FilePath $venvPython -Arguments @("-c", "import paddle; raise SystemExit(0 if paddle.is_compiled_with_cuda() else 'Installed PaddlePaddle is not compiled with CUDA')")
    Invoke-CheckedNative -FilePath $venvPython -Arguments @("-c", "import paddle; paddle.set_device('gpu'); print('Paddle CUDA device:', paddle.get_device())")
  }
}

Invoke-CheckedNative -FilePath $venvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $root "backend\requirements-ocr-intelligent.txt"))
Invoke-CheckedNative -FilePath $venvPython -Arguments @("-m", "pip", "install", "numpy<2.4,>=1.24")

if ($routeUseDirectML) {
  Invoke-CheckedNative -FilePath $venvPython -Arguments @("-m", "pip", "install", "onnxruntime-directml", "rapidocr>=3.0.0")
  Ensure-EyexDirectMLModels -Python $venvPython -ModelDir $gpuRoute.directml_model_dir -CacheRoot $writeRoots.cache_root -DisableAutoInstall:$DisableAutoDirectMLModelInstall
  Invoke-CheckedNative -FilePath $venvPython -Arguments @("-c", "import onnxruntime as ort; providers=ort.get_available_providers(); raise SystemExit(0 if 'DmlExecutionProvider' in providers else f'DmlExecutionProvider unavailable: {providers}')")
  $env:EYEX_OCR_DIRECTML_MODEL_DIR = $gpuRoute.directml_model_dir
  $directMlProbe = @'
from pathlib import Path
import os
from rapidocr import OCRVersion, RapidOCR

model_dir = Path(os.environ["EYEX_OCR_DIRECTML_MODEL_DIR"])
engine = RapidOCR(
    params={
        "Global.model_root_dir": str(model_dir),
        "EngineConfig.onnxruntime.use_dml": True,
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
    }
)
for name, component_name in {"det": "text_det", "cls": "text_cls", "rec": "text_rec"}.items():
    component = getattr(engine, component_name, None)
    session_wrapper = getattr(component, "session", None)
    session = getattr(session_wrapper, "session", None)
    active = session.get_providers() if session is not None else []
    if "DmlExecutionProvider" not in active:
        raise SystemExit(f"{name} did not activate DmlExecutionProvider; active providers={active}")
print("DirectML RapidOCR sessions ready:", model_dir)
'@
  Invoke-GeneratedPythonScript -Python $venvPython -ScriptPath (Join-Path $writeRoots.tmp_root "probe-directml-models.py") -Content $directMlProbe
}

if (!$SkipWarmup) {
  Write-Host "Warming up OCR models. This can take several minutes on the first run while model weights download."
  if ($routeUseDirectML) {
    Write-Host "DirectML PP-OCRv5 models were warmed during provider validation; skipping local PaddleOCR-VL CPU warmup on Radeon."
  } else {
    $paddleWarmup = if ($routeUseGpu) {
      "from paddleocr import PPStructureV3, PaddleOCRVL, PaddleOCR; PaddleOCR(ocr_version='PP-OCRv5', lang='ch'); PPStructureV3(); PaddleOCRVL(); print('PaddleOCR models are ready')"
    } else {
      "from paddleocr import PPStructureV3, PaddleOCR; PaddleOCR(ocr_version='PP-OCRv5', lang='ch'); PPStructureV3(); print('PaddleOCR models are ready')"
    }
    Invoke-CheckedNative -FilePath $venvPython -Arguments @("-c", $paddleWarmup)
  }
  Invoke-CheckedNative -FilePath $venvPython -Arguments @("-c", "from docling.document_converter import DocumentConverter; DocumentConverter(); print('Docling converter is ready')")
}

$ocrDevice = if ($routeUseGpu) { "gpu" } else { "cpu" }
$ocrAccelerator = $gpuRoute.accelerator
$documentAiUrl = if ($gpuRoute.remote_rocm_sidecar_url) { $gpuRoute.remote_rocm_sidecar_url } else { "http://127.0.0.1:$Port/extract" }
Set-EnvValue -Path $envPath -Name "EYEX_OCR_PROFILE" -Value $gpuRoute.ocr_profile -Overwrite
Set-EnvValue -Path $envPath -Name "EYEX_OCR_DOCUMENT_AI_URL" -Value $documentAiUrl -Overwrite
Set-EnvValue -Path $envPath -Name "EYEX_OCR_DOCUMENT_AI_TIMEOUT_SECONDS" -Value "900" -Overwrite
Set-EnvValue -Path $envPath -Name "EYEX_OCR_DOCUMENT_AI_API_KEY" -Value "" 
Set-EnvValue -Path $envPath -Name "EYEX_OCR_SIDECAR_ENGINES" -Value "" -Overwrite
Set-EnvValue -Path $envPath -Name "EYEX_OCR_DEVICE" -Value $ocrDevice -Overwrite
Set-EnvValue -Path $envPath -Name "EYEX_OCR_ACCELERATOR" -Value $ocrAccelerator -Overwrite
Set-EnvValue -Path $envPath -Name "EYEX_OCR_DIRECTML_MODEL_DIR" -Value $gpuRoute.directml_model_dir -Overwrite
Set-EnvValue -Path $envPath -Name "EYEX_OCR_GPU_ROUTE" -Value $gpuRoute.route -Overwrite
Set-EnvValue -Path $envPath -Name "EYEX_OCR_ROUTE_VERSION" -Value "ocr-route-v1" -Overwrite
Set-EnvValue -Path $envPath -Name "EYEX_OCR_MODEL_ROOT" -Value $writeRoots.model_root -Overwrite
Set-EnvValue -Path $envPath -Name "EYEX_OCR_INSTALL_CACHE_ROOT" -Value $writeRoots.cache_root -Overwrite
Set-EnvValue -Path $envPath -Name "HF_HOME" -Value $env:HF_HOME -Overwrite
Set-EnvValue -Path $envPath -Name "HUGGINGFACE_HUB_CACHE" -Value $env:HUGGINGFACE_HUB_CACHE -Overwrite
Set-EnvValue -Path $envPath -Name "PIP_CACHE_DIR" -Value $env:PIP_CACHE_DIR -Overwrite
Set-EnvValue -Path $envPath -Name "PADDLE_HOME" -Value $env:PADDLE_HOME -Overwrite
Set-EnvValue -Path $envPath -Name "PADDLEOCR_HOME" -Value $env:PADDLEOCR_HOME -Overwrite
Set-EnvValue -Path $envPath -Name "PADDLEX_HOME" -Value $env:PADDLEX_HOME -Overwrite
Set-EnvValue -Path $envPath -Name "PADDLE_PDX_CACHE_HOME" -Value $env:PADDLE_PDX_CACHE_HOME -Overwrite
Set-EnvValue -Path $envPath -Name "XDG_CACHE_HOME" -Value $env:XDG_CACHE_HOME -Overwrite
Set-EnvValue -Path $envPath -Name "TORCH_HOME" -Value $env:TORCH_HOME -Overwrite
Set-EnvValue -Path $envPath -Name "PADDLE_PDX_MODEL_SOURCE" -Value $PaddleModelSource -Overwrite
Set-EnvValue -Path $envPath -Name "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK" -Value "True" -Overwrite
Set-EnvValue -Path $envPath -Name "DISABLE_MODEL_SOURCE_CHECK" -Value "True" -Overwrite

if ($UseDeepSeek) {
  Set-EnvValue -Path $envPath -Name "EYEX_MODEL_PROFILE" -Value "deepseek_v4_flash" -Overwrite
  if ($DeepSeekApiKey.Trim()) {
    Set-EnvValue -Path $envPath -Name "EYEX_DEEPSEEK_API_KEY" -Value $DeepSeekApiKey.Trim() -Overwrite
  }
}

Write-Host "OCR sidecar environment installed."
Write-Host "Configured .env: EYEX_OCR_PROFILE=$($gpuRoute.ocr_profile)"
Write-Host "Configured .env: EYEX_OCR_DOCUMENT_AI_URL=$documentAiUrl"
Write-Host "Configured .env: EYEX_OCR_DEVICE=$ocrDevice"
Write-Host "Configured .env: EYEX_OCR_ACCELERATOR=$ocrAccelerator"
Write-Host "Configured .env: EYEX_OCR_GPU_ROUTE=$($gpuRoute.route)"
if ($UseDeepSeek) {
  Write-Host "Configured .env: EYEX_MODEL_PROFILE=deepseek_v4_flash"
}

if ($shouldStartSidecar -and $gpuRoute.route -ne "amd_rocm_remote") {
  & (Join-Path $scriptDir "start-ocr-sidecar.ps1") -VenvPath $VenvPath -Port $Port -OcrDevice $ocrDevice -OcrAccelerator $ocrAccelerator
} elseif ($shouldStartSidecar) {
  Write-Host "Skipping local sidecar start because OCR is configured for remote ROCm sidecar: $documentAiUrl"
}
