from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTER = ROOT / "scripts" / "ocr-gpu-routing.ps1"
INSTALLER = ROOT / "scripts" / "install-intelligent-ocr.ps1"
OCR_EVAL_WRAPPER = ROOT / "scripts" / "run-ocr-eval.ps1"


def _powershell_json(script: str) -> dict:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _powershell_fails(script: str) -> str:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    return completed.stderr + completed.stdout


def test_nvidia_cuda_route_requires_cuda_gpu_install():
    payload = _powershell_json(
        f"""
. '{ROUTER}'
$route = Resolve-EyexOcrGpuRoute `
  -GpuJson '[{{"Name":"NVIDIA GeForce RTX 4070","AdapterCompatibility":"NVIDIA"}}]' `
  -CommandJson '{{"nvidia-smi":true,"docker":false,"wsl":false,"rocminfo":false,"rocm-smi":false,"hipcc":false}}' `
  -GpuPolicy Require
$route | ConvertTo-Json -Depth 8
"""
    )

    assert payload["route"] == "nvidia_cuda"
    assert payload["use_gpu"] is True
    assert payload["use_directml"] is False
    assert payload["accelerator"] == "cuda"
    assert payload["can_guarantee_gpu"] is True


def test_amd_radeon_directml_route_uses_existing_project_model_dir(tmp_path):
    model_dir = tmp_path / "ppocrv5"
    model_dir.mkdir()
    (model_dir / "ch_PP-OCRv5_det_server.onnx").write_bytes(b"det")
    (model_dir / "ch_PP-OCRv5_rec_server.onnx").write_bytes(b"rec")

    payload = _powershell_json(
        f"""
. '{ROUTER}'
$route = Resolve-EyexOcrGpuRoute `
  -ProjectRoot '{tmp_path}' `
  -GpuJson '[{{"Name":"AMD Radeon RX 6600","AdapterCompatibility":"Advanced Micro Devices, Inc."}}]' `
  -CommandJson '{{"nvidia-smi":false,"docker":false,"wsl":true,"rocminfo":false,"rocm-smi":false,"hipcc":false}}' `
  -DirectMLModelDir '{model_dir}' `
  -GpuPolicy Require
$route | ConvertTo-Json -Depth 8
"""
    )

    assert payload["route"] == "amd_directml"
    assert payload["use_gpu"] is False
    assert payload["use_directml"] is True
    assert payload["accelerator"] == "directml"
    assert payload["ocr_profile"] == "windows_radeon_balanced"
    assert payload["directml_model_dir"] == str(model_dir)
    assert payload["can_guarantee_gpu"] is True
    assert payload["needs_directml_model_install"] is False


def test_amd_radeon_directml_route_auto_prepares_models_inside_project(tmp_path):
    payload = _powershell_json(
        f"""
. '{ROUTER}'
$route = Resolve-EyexOcrGpuRoute `
  -ProjectRoot '{tmp_path}' `
  -GpuJson '[{{"Name":"AMD Radeon RX 6600","AdapterCompatibility":"Advanced Micro Devices, Inc."}}]' `
  -CommandJson '{{"nvidia-smi":false,"docker":false,"wsl":true,"rocminfo":false,"rocm-smi":false,"hipcc":false}}' `
  -GpuPolicy Require
$route | ConvertTo-Json -Depth 8
"""
    )

    assert payload["route"] == "amd_directml"
    assert payload["accelerator"] == "directml"
    assert payload["can_guarantee_gpu"] is True
    assert payload["needs_directml_model_install"] is True
    assert Path(payload["directml_model_dir"]).is_relative_to(tmp_path)
    assert Path(payload["directml_model_dir"]).parts[-3:] == ("var", "models", "ppocrv5-directml-server")


def test_amd_radeon_ignores_remote_rocm_vl_url_while_vl_is_disabled(tmp_path):
    payload = _powershell_json(
        f"""
. '{ROUTER}'
$route = Resolve-EyexOcrGpuRoute `
  -ProjectRoot '{tmp_path}' `
  -GpuJson '[{{"Name":"AMD Radeon RX 6600","AdapterCompatibility":"Advanced Micro Devices, Inc."}}]' `
  -CommandJson '{{"nvidia-smi":false,"docker":false,"wsl":true,"rocminfo":false,"rocm-smi":false,"hipcc":false}}' `
  -RemoteRocmSidecarUrl 'http://10.0.0.8:8765/extract' `
  -GpuPolicy Require
$route | ConvertTo-Json -Depth 8
"""
    )

    assert payload["route"] == "amd_directml"
    assert payload["ocr_profile"] == "windows_radeon_balanced"
    assert payload["accelerator"] == "directml"
    assert payload["use_directml"] is True
    assert payload["remote_rocm_sidecar_url"] == ""
    assert payload["can_guarantee_gpu"] is True
    assert payload["needs_directml_model_install"] is True


def test_amd_radeon_route_ignores_project_env_remote_vl_url_while_vl_is_disabled(tmp_path):
    (tmp_path / ".env").write_text(
        "EYEX_OCR_PADDLEOCR_VL_URL=http://10.0.0.9:8765/extract\n",
        encoding="utf-8",
    )

    payload = _powershell_json(
        f"""
. '{ROUTER}'
$route = Resolve-EyexOcrGpuRoute `
  -ProjectRoot '{tmp_path}' `
  -GpuJson '[{{"Name":"AMD Radeon RX 6600","AdapterCompatibility":"Advanced Micro Devices, Inc."}}]' `
  -CommandJson '{{"nvidia-smi":false,"docker":false,"wsl":true,"rocminfo":false,"rocm-smi":false,"hipcc":false}}' `
  -GpuPolicy Require
$route | ConvertTo-Json -Depth 8
"""
    )

    assert payload["route"] == "amd_directml"
    assert payload["remote_rocm_sidecar_url"] == ""
    assert payload["use_directml"] is True
    assert payload["can_guarantee_gpu"] is True


def test_amd_radeon_require_gpu_fails_without_directml_assets_when_auto_prepare_disabled(tmp_path):
    message = _powershell_fails(
        f"""
. '{ROUTER}'
$route = Resolve-EyexOcrGpuRoute `
  -ProjectRoot '{tmp_path}' `
  -GpuJson '[{{"Name":"AMD Radeon RX 6600","AdapterCompatibility":"Advanced Micro Devices, Inc."}}]' `
  -CommandJson '{{"nvidia-smi":false,"docker":false,"wsl":true,"rocminfo":false,"rocm-smi":false,"hipcc":false}}' `
  -DisableAutoDirectMLModelInstall `
  -GpuPolicy Require
Assert-EyexOcrGpuRoute -Route $route -GpuPolicy Require
"""
    )

    assert "DirectML model directory" in message


def test_require_gpu_fails_when_no_supported_gpu_route_exists():
    message = _powershell_fails(
        f"""
. '{ROUTER}'
$route = Resolve-EyexOcrGpuRoute `
  -GpuJson '[]' `
  -CommandJson '{{"nvidia-smi":false,"docker":false,"wsl":false,"rocminfo":false,"rocm-smi":false,"hipcc":false}}' `
  -GpuPolicy Require
Assert-EyexOcrGpuRoute -Route $route -GpuPolicy Require
"""
    )

    assert "No supported GPU OCR route" in message


def test_directml_model_dir_must_remain_inside_project(tmp_path):
    outside = tmp_path.parent / "outside-ppocrv5"
    outside.mkdir(exist_ok=True)
    (outside / "ch_PP-OCRv5_det_server.onnx").write_bytes(b"det")
    (outside / "ch_PP-OCRv5_rec_server.onnx").write_bytes(b"rec")

    message = _powershell_fails(
        f"""
. '{ROUTER}'
$route = Resolve-EyexOcrGpuRoute `
  -ProjectRoot '{tmp_path}' `
  -GpuJson '[{{"Name":"AMD Radeon RX 6600","AdapterCompatibility":"Advanced Micro Devices, Inc."}}]' `
  -CommandJson '{{"nvidia-smi":false,"docker":false,"wsl":true,"rocminfo":false,"rocm-smi":false,"hipcc":false}}' `
  -DirectMLModelDir '{outside}' `
  -GpuPolicy Require
Assert-EyexOcrGpuRoute -Route $route -GpuPolicy Require
"""
    )

    # PowerShell may wrap the error message at arbitrary column boundaries,
    # inserting newlines mid-word. Normalize by collapsing all whitespace.
    normalized = " ".join(message.split())
    assert "inside the EYEX project directory" in normalized


def test_installer_keeps_model_and_cache_writes_under_project_var_dirs():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "var\\models" in text
    assert "var\\cache\\ocr-install" in text
    assert "HF_HOME" in text
    assert "HUGGINGFACE_HUB_CACHE" in text
    assert "PADDLE_HOME" in text
    assert "PADDLEOCR_HOME" in text
    assert "PADDLEX_HOME" in text
    assert "PADDLE_PDX_CACHE_HOME" in text
    assert "PIP_CACHE_DIR" in text
    assert "EYEX_OCR_PADDLEOCR_VL_URL" in text


def test_installer_is_fully_automatic_without_arguments():
    text = INSTALLER.read_text(encoding="utf-8")
    wrapper = (ROOT / "install-ocr.cmd").read_text(encoding="utf-8")

    assert '[string]$PythonExe = "py"' in text
    assert '[string[]]$PythonArgs = @("-3.11")' in text
    assert "[switch]$NoStartSidecar" in text
    assert "$shouldStartServices = !$NoStartSidecar" in text
    assert "scripts\\install-intelligent-ocr.ps1\" %*" in wrapper
    assert "Resolve-EyexOcrRemoteRocmSidecarUrl" not in text


def test_installer_removes_stale_runtime_engine_override_env():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "function Remove-EnvValue" in text
    assert 'Remove-EnvValue -Path $envPath -Name "EYEX_OCR_SIDECAR_ENGINES"' in text
    assert 'Set-EnvValue -Path $envPath -Name "EYEX_OCR_SIDECAR_ENGINES"' not in text


def test_ocr_eval_wrapper_prefers_project_ocr_venv_python():
    text = OCR_EVAL_WRAPPER.read_text(encoding="utf-8")

    assert '[string]$PythonExe = ""' in text
    assert '$defaultOcrPython = Join-Path $root ".venv-ocr\\Scripts\\python.exe"' in text
    assert 'if ($PythonExe.Trim())' in text
    assert 'elseif (Test-Path $defaultOcrPython)' in text


def test_installer_does_not_recreate_existing_venv_or_ignore_native_failures():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "function Invoke-CheckedNative" in text
    assert "foreach ($processId in $connections)" in text
    assert "foreach ($pid in $connections)" not in text
    assert "if (!(Test-Path $venvPython))" in text
    assert "OCR sidecar venv already exists" in text
    assert 'if (!(Test-Path $venvPython)) {' in text
    assert 'Invoke-BasePython @("-m", "venv", $venv)' in text


def test_installer_runs_generated_python_files_instead_of_inline_multiline_c():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "prepare-directml-models.py" in text
    assert "probe-directml-models.py" in text
    assert "RapidOCR" in text
    assert "ModelType.SERVER" in text
    assert '"Global.max_side_len": 1536' in text
    assert '"directml_safe_mode": True' in text
    assert '"tile_max_side_len": 1536' in text
    assert "ch_PP-OCRv5_det_server.onnx" in text
    assert "ch_PP-OCRv5_rec_server.onnx" in text
    assert "paddle2onnx" not in text.lower()
    assert "& $Python -c $prepareDirectMLModels" not in text
    assert "& $venvPython -c $directMlProbe" not in text


def test_installer_skips_cpu_vl_warmup_on_directml_route():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "skipping heavyweight local layout/Docling CPU warmup on Radeon" in text
    assert "if ($routeUseDirectML)" in text
    directml_branch, warmup_tail = text.split('if ($routeUseDirectML)', 1)[1].split('$ocrAccelerator = $gpuRoute.accelerator', 1)
    assert "DocumentConverter" in directml_branch
    assert "Invoke-CheckedNative -FilePath $venvPython -Arguments @(\"-c\", \"from docling.document_converter" in directml_branch


def test_installer_requires_remote_gpu_url_for_strict_gpu_route():
    text = INSTALLER.read_text(encoding="utf-8")

    assert 'Write-Warning "PaddleOCR-VL is temporarily disabled in EYEX; ignoring -RemoteRocmSidecarUrl."' in text
    assert "EYEX_OCR_DOCUMENT_AI_URL" in text


def test_unified_start_script_starts_ocr_sidecar_without_undefined_device_variable():
    text = (ROOT / "scripts" / "start.ps1").read_text(encoding="utf-8")

    assert "EYEX OCR sidecar" in text
    assert "EYEX_OCR_ACCELERATOR" in text
    assert "$OcrDevice" not in text


def test_probe_ignores_remote_vl_resolution_while_vl_is_disabled():
    text = (ROOT / "scripts" / "probe-amd-ocr.ps1").read_text(encoding="utf-8")

    assert "Resolve-EyexOcrRemoteRocmSidecarUrl" not in text
    assert 'RemoteRocmSidecarUrl ""' in text
    assert "$output = $code | & $PythonExe -" in text


def test_installer_does_not_manage_rocm_vl_or_docker_by_default():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "paddleocr-vl:latest-amd-gpu" not in text
    assert "paddleocr-genai-vllm-server:latest-amd-gpu" not in text
    assert "var\\rocm-vl-sidecar" not in text
    assert "var\\models\\paddleocr-vl-rocm" not in text
    assert "var\\cache\\paddleocr-vl-rocm" not in text
    assert "EYEX_OCR_PADDLEOCR_VL_URL" in text
    assert "/layout-parsing" not in text
    assert "docker compose" not in text
    assert "Docker Desktop" not in text
    assert "C:\\Users" not in text


def test_installer_does_not_auto_bootstrap_rocm_vl_sidecar_without_arguments():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "Resolve-EyexOcrGpuRoute" in text
    assert "Checking optional PaddleOCR-VL AMD/ROCm sidecar route." not in text
    assert "Try-Prepare-EyexRocmVlSidecar -Root" not in text
    assert '$resolvedRemoteRocmSidecarUrl = ""' in text


def test_installer_keeps_docker_bootstrap_out_of_default_install_flow():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "Installing EYEX intelligent OCR sidecar" in text
    main_flow = text.split('Write-Host "Installing EYEX intelligent OCR sidecar under $venv"', 1)[1]
    assert "Try-Prepare-EyexRocmVlSidecar -Root" not in main_flow
    assert "Ensure-EyexDockerDesktop -Root" not in main_flow
    assert "docker compose" not in main_flow


def test_probe_reports_paddleocr_vl_disabled_without_sidecar_instructions():
    text = (ROOT / "scripts" / "probe-amd-ocr.ps1").read_text(encoding="utf-8")

    assert "paddleocr_vl" in text
    assert "status = \"disabled\"" in text
    assert "compose.yaml" not in text
    assert "paddleocr_vl_rocm_sidecar" not in text


def test_ocr_sidecar_requirements_avoid_backend_pin_conflicts():
    install_text = INSTALLER.read_text(encoding="utf-8")
    req_text = (ROOT / "backend" / "requirements-ocr-intelligent.txt").read_text(encoding="utf-8")

    assert 'backend\\requirements.txt' not in install_text
    assert "pydantic-settings>=2.14.0" in req_text
    assert "PyYAML==6.0.2" in req_text
    assert "httpx==0.28.1" in req_text
    assert "rapidocr>=3.0.0" in req_text
