function ConvertFrom-EyexJson {
  param(
    [string]$Json,
    $Default
  )
  if (!$Json -or !$Json.Trim()) {
    return $Default
  }
  try {
    return $Json | ConvertFrom-Json
  } catch {
    return $Default
  }
}

function Test-EyexCommandAvailable {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Resolve-EyexAbsolutePath {
  param(
    [string]$Path,
    [string]$BasePath = ""
  )
  $base = if ($BasePath -and $BasePath.Trim()) { $BasePath } else { (Get-Location).Path }
  if (!$Path -or !$Path.Trim()) {
    return [System.IO.Path]::GetFullPath($base)
  }
  $resolved = Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue
  if ($resolved) {
    return [System.IO.Path]::GetFullPath($resolved.Path)
  }
  if ([System.IO.Path]::IsPathRooted($Path)) {
    return [System.IO.Path]::GetFullPath($Path)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $base $Path))
}

function Test-EyexPathUnderRoot {
  param(
    [string]$Path,
    [string]$Root
  )
  try {
    $trimChars = [char[]]@([char]92, [char]47)
    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd($trimChars)
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd($trimChars)
    return $fullPath.Equals($fullRoot, [System.StringComparison]::OrdinalIgnoreCase) -or $fullPath.StartsWith($fullRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
  } catch {
    return $false
  }
}

function Get-EyexDefaultDirectMLModelDir {
  param([string]$ProjectRoot = "")
  $root = Resolve-EyexAbsolutePath -Path $ProjectRoot
  return [System.IO.Path]::GetFullPath((Join-Path $root "var\models\ppocrv5-directml"))
}

function Get-EyexGpuInventory {
  $items = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Select-Object Name, AdapterCompatibility, DriverVersion, AdapterRAM)
  return $items
}

function Get-EyexOcrCommandStatus {
  return [pscustomobject]@{
    "nvidia-smi" = Test-EyexCommandAvailable "nvidia-smi"
    docker = Test-EyexCommandAvailable "docker"
    wsl = Test-EyexCommandAvailable "wsl"
    rocminfo = Test-EyexCommandAvailable "rocminfo"
    "rocm-smi" = Test-EyexCommandAvailable "rocm-smi"
    hipcc = Test-EyexCommandAvailable "hipcc"
  }
}

function Test-EyexDirectMLModelDir {
  param([string]$Path)
  if (!$Path -or !$Path.Trim()) {
    return $false
  }
  $resolved = Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue
  if (!$resolved) {
    return $false
  }
  return (Test-Path -LiteralPath (Join-Path $resolved.Path "det.onnx")) -and (Test-Path -LiteralPath (Join-Path $resolved.Path "rec.onnx"))
}

function Test-EyexGpuName {
  param(
    $Gpu,
    [string]$Pattern
  )
  $name = [string]($Gpu.Name)
  $adapter = [string]($Gpu.AdapterCompatibility)
  return $name -match $Pattern -or $adapter -match $Pattern
}

function Resolve-EyexOcrGpuRoute {
  [CmdletBinding()]
  param(
    [string]$GpuJson = "",
    [string]$CommandJson = "",
    [string]$ProjectRoot = "",
    [ValidateSet("Auto", "Require", "Off")]
    [string]$GpuPolicy = "Require",
    [string]$DirectMLModelDir = "",
    [string]$RemoteRocmSidecarUrl = "",
    [switch]$DisableAutoDirectMLModelInstall
  )

  $projectRootPath = Resolve-EyexAbsolutePath -Path $ProjectRoot
  $directMLCandidate = if ($DirectMLModelDir -and $DirectMLModelDir.Trim()) {
    Resolve-EyexAbsolutePath -Path $DirectMLModelDir -BasePath $projectRootPath
  } else {
    Get-EyexDefaultDirectMLModelDir -ProjectRoot $projectRootPath
  }
  $gpus = if ($GpuJson -and $GpuJson.Trim() -eq "[]") {
    @()
  } else {
    @(ConvertFrom-EyexJson -Json $GpuJson -Default (Get-EyexGpuInventory))
  }
  $commands = ConvertFrom-EyexJson -Json $CommandJson -Default (Get-EyexOcrCommandStatus)
  $hasNvidia = @($gpus | Where-Object { Test-EyexGpuName $_ "NVIDIA|GeForce|RTX|Quadro|Tesla" }).Count -gt 0
  $hasAmd = @($gpus | Where-Object { Test-EyexGpuName $_ "AMD|Radeon|Advanced Micro Devices" }).Count -gt 0
  $hasAnyGpu = @($gpus).Count -gt 0
  $hasNvidiaSmi = [bool]($commands.'nvidia-smi')
  $directMLDirInsideProject = Test-EyexPathUnderRoot -Path $directMLCandidate -Root $projectRootPath
  $hasDirectMLAssets = $directMLDirInsideProject -and (Test-EyexDirectMLModelDir -Path $directMLCandidate)
  $canAutoInstallDirectMLAssets = !$DisableAutoDirectMLModelInstall
  $hasRemoteRocm = [bool]($RemoteRocmSidecarUrl -and $RemoteRocmSidecarUrl.Trim())

  if ($GpuPolicy -eq "Off") {
    return [pscustomobject]@{
      route = "cpu"
      reason = "GPU policy is Off"
      ocr_profile = "cpu_stable"
      accelerator = "cpu"
      use_gpu = $false
      use_directml = $false
      can_guarantee_gpu = $false
      directml_model_dir = ""
      remote_rocm_sidecar_url = ""
      needs_directml_model_install = $false
      project_root = $projectRootPath
      required_action = ""
    }
  }

  if ($hasNvidia -and $hasNvidiaSmi) {
    return [pscustomobject]@{
      route = "nvidia_cuda"
      reason = "NVIDIA GPU and nvidia-smi detected; install Paddle CUDA wheel and validate paddle.set_device('gpu')."
      ocr_profile = "cuda_paddle"
      accelerator = "cuda"
      use_gpu = $true
      use_directml = $false
      can_guarantee_gpu = $true
      directml_model_dir = ""
      remote_rocm_sidecar_url = ""
      needs_directml_model_install = $false
      project_root = $projectRootPath
      required_action = ""
    }
  }

  if ($hasAmd -and $hasRemoteRocm) {
    return [pscustomobject]@{
      route = "amd_rocm_remote"
      reason = "AMD GPU detected; using configured remote ROCm PaddleOCR-VL sidecar."
      ocr_profile = "rocm_remote_vl"
      accelerator = "remote"
      use_gpu = $false
      use_directml = $false
      can_guarantee_gpu = $true
      directml_model_dir = ""
      remote_rocm_sidecar_url = $RemoteRocmSidecarUrl.Trim()
      needs_directml_model_install = $false
      project_root = $projectRootPath
      required_action = ""
    }
  }

  if (($hasAmd -or $hasAnyGpu) -and !$directMLDirInsideProject) {
    $vendorRoute = if ($hasAmd) { "amd_directml" } else { "windows_directml" }
    return [pscustomobject]@{
      route = $vendorRoute
      reason = "DirectML model directory is outside the EYEX project directory."
      ocr_profile = "windows_radeon_balanced"
      accelerator = "directml"
      use_gpu = $false
      use_directml = $true
      can_guarantee_gpu = $false
      directml_model_dir = $directMLCandidate
      remote_rocm_sidecar_url = ""
      needs_directml_model_install = !$hasDirectMLAssets
      project_root = $projectRootPath
      required_action = "DirectML model directory must stay inside the EYEX project directory: $projectRootPath"
    }
  }

  if ($hasAmd -and $hasDirectMLAssets) {
    return [pscustomobject]@{
      route = "amd_directml"
      reason = "AMD Radeon detected; using PP-OCRv5 ONNX with ONNX Runtime DirectML."
      ocr_profile = "windows_radeon_balanced"
      accelerator = "directml"
      use_gpu = $false
      use_directml = $true
      can_guarantee_gpu = $true
      directml_model_dir = $directMLCandidate
      remote_rocm_sidecar_url = ""
      needs_directml_model_install = $false
      project_root = $projectRootPath
      required_action = ""
    }
  }

  if ($hasAmd -and $canAutoInstallDirectMLAssets) {
    return [pscustomobject]@{
      route = "amd_directml"
      reason = "AMD Radeon detected; installer will prepare RapidOCR PP-OCRv5 ONNX models under the EYEX project directory."
      ocr_profile = "windows_radeon_balanced"
      accelerator = "directml"
      use_gpu = $false
      use_directml = $true
      can_guarantee_gpu = $true
      directml_model_dir = $directMLCandidate
      remote_rocm_sidecar_url = ""
      needs_directml_model_install = $true
      project_root = $projectRootPath
      required_action = ""
    }
  }

  if ($hasAmd) {
    return [pscustomobject]@{
      route = "amd_directml"
      reason = "AMD Radeon detected, but DirectML PP-OCRv5 ONNX assets are missing and automatic model preparation is disabled."
      ocr_profile = "windows_radeon_balanced"
      accelerator = "directml"
      use_gpu = $false
      use_directml = $true
      can_guarantee_gpu = $false
      directml_model_dir = $directMLCandidate
      remote_rocm_sidecar_url = ""
      needs_directml_model_install = $true
      project_root = $projectRootPath
      required_action = "DirectML model directory must contain RapidOCR PP-OCRv5 ONNX files or det.onnx and rec.onnx aliases. Enable automatic model preparation, or pass -RemoteRocmSidecarUrl for a validated ROCm/VL sidecar."
    }
  }

  if ($hasAnyGpu -and $hasDirectMLAssets) {
    return [pscustomobject]@{
      route = "windows_directml"
      reason = "Non-NVIDIA GPU detected; using PP-OCRv5 ONNX with ONNX Runtime DirectML."
      ocr_profile = "windows_radeon_balanced"
      accelerator = "directml"
      use_gpu = $false
      use_directml = $true
      can_guarantee_gpu = $true
      directml_model_dir = $directMLCandidate
      remote_rocm_sidecar_url = ""
      needs_directml_model_install = $false
      project_root = $projectRootPath
      required_action = ""
    }
  }

  if ($hasAnyGpu -and $canAutoInstallDirectMLAssets) {
    return [pscustomobject]@{
      route = "windows_directml"
      reason = "GPU detected; installer will prepare RapidOCR PP-OCRv5 ONNX models under the EYEX project directory for ONNX Runtime DirectML."
      ocr_profile = "windows_radeon_balanced"
      accelerator = "directml"
      use_gpu = $false
      use_directml = $true
      can_guarantee_gpu = $true
      directml_model_dir = $directMLCandidate
      remote_rocm_sidecar_url = ""
      needs_directml_model_install = $true
      project_root = $projectRootPath
      required_action = ""
    }
  }

  return [pscustomobject]@{
    route = "none"
    reason = "No supported GPU OCR route detected."
    ocr_profile = "cpu_stable"
    accelerator = "cpu"
    use_gpu = $false
    use_directml = $false
    can_guarantee_gpu = $false
    directml_model_dir = ""
    remote_rocm_sidecar_url = ""
    needs_directml_model_install = $false
    project_root = $projectRootPath
    required_action = "No supported GPU OCR route. Use NVIDIA CUDA, enable automatic DirectML PP-OCRv5 model preparation, or configure a remote ROCm PaddleOCR-VL sidecar."
  }
}

function Assert-EyexOcrGpuRoute {
  param(
    [Parameter(Mandatory = $true)]$Route,
    [ValidateSet("Auto", "Require", "Off")]
    [string]$GpuPolicy = "Require"
  )
  if ($GpuPolicy -ne "Require") {
    return
  }
  if (!$Route.can_guarantee_gpu) {
    $action = [string]$Route.required_action
    if (!$action.Trim()) {
      $action = "No supported GPU OCR route."
    }
    throw $action
  }
}
