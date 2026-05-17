$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location $root

function Import-EyexDotEnv {
  param([string]$Path)
  if (!(Test-Path -LiteralPath $Path)) {
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

function Get-EyexPortOwnerPids {
  param([int]$Port)
  return @(Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -gt 0 } |
    Select-Object -ExpandProperty OwningProcess -Unique)
}

function Start-EyexProcessIfMissing {
  param(
    [string]$Name,
    [int]$Port,
    [string]$FilePath,
    [string]$ArgumentList,
    [string]$WorkingDirectory,
    [string]$StdoutPath,
    [string]$StderrPath
  )
  $ownerPids = Get-EyexPortOwnerPids -Port $Port
  if ($ownerPids.Count -gt 0) {
    foreach ($ownerPid in $ownerPids) {
      if (Test-EyexProcess -ProcessId $ownerPid) {
        Write-Host "$Name already running on port $Port (process $ownerPid)."
        return
      }
    }
    throw "$Name cannot start because port $Port is used by non-EYEX process(es): $($ownerPids -join ', ')."
  }
  $process = Start-Process `
    -WindowStyle Hidden `
    -FilePath $FilePath `
    -ArgumentList $ArgumentList `
    -WorkingDirectory $WorkingDirectory `
    -RedirectStandardOutput $StdoutPath `
    -RedirectStandardError $StderrPath `
    -PassThru
  Write-Host "$Name started on port $Port (process $($process.Id))."
}

function Wait-EyexHttp {
  param(
    [string]$Uri,
    [int]$TimeoutSeconds = 30,
    [string]$Name = "service"
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $lastError = $null
  while ((Get-Date) -lt $deadline) {
    try {
      return Invoke-RestMethod -Uri $Uri -TimeoutSec 2
    } catch {
      $lastError = $_.Exception.Message
      Start-Sleep -Milliseconds 750
    }
  }
  throw "$Name did not become ready at $Uri within $TimeoutSeconds seconds. Last error: $lastError"
}

function Test-EyexHttpReady {
  param([string]$Uri)
  try {
    Invoke-RestMethod -Uri $Uri -TimeoutSec 3 | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Get-EyexHealthUrl {
  param([string]$Endpoint)
  if (!$Endpoint) {
    return ""
  }
  try {
    $uri = [System.Uri]$Endpoint
    return "$($uri.Scheme)://$($uri.Authority)/health"
  } catch {
    return ""
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

  # Sync PaddleX models from user's default cache to runtime cache.
  # PPStructureV3 downloads ~15 models (hundreds of MB each) on first init.
  # Without this sync, the sidecar times out waiting for downloads and crashes.
  $defaultPaddlexModels = Join-Path $env:USERPROFILE ".paddlex\official_models"
  $runtimePaddlexModels = Join-Path $env:PADDLEX_HOME "official_models"
  if ((Test-Path $defaultPaddlexModels) -and ($defaultPaddlexModels -ne $runtimePaddlexModels)) {
    New-Item -ItemType Directory -Force -Path $runtimePaddlexModels | Out-Null
    $existingModels = @(Get-ChildItem $runtimePaddlexModels -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
    foreach ($model in Get-ChildItem $defaultPaddlexModels -Directory -ErrorAction SilentlyContinue) {
      if ($model.Name -notin $existingModels) {
        Copy-Item -Recurse -Force $model.FullName $runtimePaddlexModels
        Write-Host "Synced PaddleX model: $($model.Name)"
      }
    }
  }
}


function Write-EyexOcrHealthSummary {
  param([object]$Health)
  if ($null -eq $Health -or $null -eq $Health.strong_pipeline_readiness) {
    return
  }
  $readiness = $Health.strong_pipeline_readiness
  if ($readiness.ready) {
    Write-Host "OCR strong pipeline: ready"
    return
  }
  Write-Host "OCR strong pipeline: not ready"
  if ($readiness.stages) {
    foreach ($property in $readiness.stages.PSObject.Properties) {
      $stage = $property.Name
      $status = $property.Value
      if (!$status.ready) {
        Write-Host " - $stage / $($status.engine_id): $($status.reason)"
      }
    }
  }
}

Import-EyexDotEnv (Join-Path $root ".env")
Set-OcrProjectRuntimeRoots -Root $root

$logDir = Join-Path $root "logs"
$frontendDir = Join-Path $root "frontend"
New-Item -ItemType Directory -Force $logDir | Out-Null

$python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
$ocrPython = Join-Path $root ".venv-ocr\Scripts\python.exe"

if (Test-Path -LiteralPath $ocrPython) {
  $env:PADDLE_PDX_MODEL_SOURCE = if ($env:PADDLE_PDX_MODEL_SOURCE) { $env:PADDLE_PDX_MODEL_SOURCE } else { "BOS" }
  $env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
  $env:DISABLE_MODEL_SOURCE_CHECK = "True"
  if (!$env:EYEX_OCR_ACCELERATOR) { $env:EYEX_OCR_ACCELERATOR = "auto" }

  # Add torch DLL directories to PATH so Start-Process child processes can find them.
  # os.add_dll_directory() in torch/__init__.py doesn't propagate to child processes
  # launched via Start-Process -WindowStyle Hidden, causing shm.dll load failures.
  $ocrSitePackages = Join-Path (Split-Path $ocrPython) "..\Lib\site-packages"
  $torchLibDir = Join-Path $ocrSitePackages "torch\lib"
  $ocrScriptsDir = Split-Path $ocrPython
  if (Test-Path $torchLibDir) {
    $torchLibDir = (Resolve-Path $torchLibDir).Path
    $ocrScriptsDir = (Resolve-Path $ocrScriptsDir).Path
    $env:PATH = "$torchLibDir;$ocrScriptsDir;$($env:PATH)"
  }

  Start-EyexProcessIfMissing `
    -Name "EYEX OCR sidecar" `
    -Port 8765 `
    -FilePath $ocrPython `
    -ArgumentList "-m uvicorn ocr_sidecar.main:app --app-dir backend --host 127.0.0.1 --port 8765" `
    -WorkingDirectory $root `
    -StdoutPath (Join-Path $logDir "ocr-sidecar.log") `
    -StderrPath (Join-Path $logDir "ocr-sidecar.err.log")
  try {
    $ocrHealth = Wait-EyexHttp -Uri "http://127.0.0.1:8765/health" -TimeoutSeconds 45 -Name "OCR sidecar"
    Write-EyexOcrHealthSummary -Health $ocrHealth
  } catch {
    Write-Host "OCR sidecar readiness check failed: $($_.Exception.Message)"
  }
} else {
  Write-Host "OCR sidecar venv not found at $ocrPython. Run .\install-ocr.cmd before processing scanned PDFs/images."
}

Start-EyexProcessIfMissing `
  -Name "EYEX backend" `
  -Port 8000 `
  -FilePath $python `
  -ArgumentList "-m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000" `
  -WorkingDirectory $root `
  -StdoutPath (Join-Path $logDir "backend.log") `
  -StderrPath (Join-Path $logDir "backend.err.log")

try {
  Wait-EyexHttp -Uri "http://127.0.0.1:8000/api/health" -TimeoutSeconds 30 -Name "backend" | Out-Null
  Write-Host "Backend health: ready"
} catch {
  Write-Host "Backend health check failed: $($_.Exception.Message)"
}

Start-EyexProcessIfMissing `
  -Name "EYEX frontend" `
  -Port 5173 `
  -FilePath "npm.cmd" `
  -ArgumentList "run dev -- --host 127.0.0.1" `
  -WorkingDirectory $frontendDir `
  -StdoutPath (Join-Path $logDir "frontend.log") `
  -StderrPath (Join-Path $logDir "frontend.err.log")

try {
  Wait-EyexHttp -Uri "http://127.0.0.1:5173" -TimeoutSeconds 30 -Name "frontend" | Out-Null
  Write-Host "Frontend health: ready"
} catch {
  Write-Host "Frontend health check failed: $($_.Exception.Message)"
}

Write-Host "EYEX backend: http://127.0.0.1:8000"
Write-Host "EYEX frontend: http://localhost:5173"
Write-Host "Stop all EYEX services: .\stop.cmd"
