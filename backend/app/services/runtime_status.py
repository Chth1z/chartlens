from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from app.core.config_loader import load_ocr_profile
from app.core.settings import settings

RuntimeJsonGetter = Callable[[str, float], dict[str, Any]]
SIDECAR_API_CONTRACT_VERSION = "eyex-ocr-sidecar-v2"
SIDECAR_LAYOUT_POLICY_VERSION = "ocr-canonical-layout-v3"
SIDECAR_RESTART_COMMANDS = ".\\stop.cmd, then .\\start.cmd"


def build_runtime_services(http_get_json: RuntimeJsonGetter | None = None) -> dict[str, Any]:
    """Return lightweight readiness facts for local EYEX services.

    This must stay cheap: it may call sidecar /health, but it must not import or
    initialize OCR models in the backend process.
    """

    return {
        "backend": {
            "key": "backend",
            "label": "后端 API",
            "ready": True,
            "status": "ready",
            "summary": "后端 API 已就绪",
            "endpoint": "http://127.0.0.1:8000/api/health",
            "checks": [],
            "actions": [],
        },
        "ocr": build_ocr_runtime_status(http_get_json=http_get_json),
        "frontend": {
            "key": "frontend",
            "label": "前端页面",
            "ready": None,
            "status": "external",
            "summary": "前端由本地 Vite 进程提供，后端无法直接确认浏览器页面状态",
            "endpoint": "http://localhost:5173",
            "checks": [],
            "actions": [{"label": "启动完整应用", "command": ".\\start.cmd"}],
        },
    }


def build_ocr_runtime_status(http_get_json: RuntimeJsonGetter | None = None) -> dict[str, Any]:
    profile = _active_profile_payload()
    endpoint = settings.ocr_document_ai_url.strip() if settings.ocr_document_ai_url else ""
    profile_id = str(profile.get("profile_id") or settings.ocr_profile)
    base_payload: dict[str, Any] = {
        "key": "ocr",
        "label": "智能文档 OCR",
        "profile_id": profile_id,
        "pipeline_stages": profile.get("pipeline_stages", []),
        "stage_models": profile.get("stage_models", {}),
        "endpoint": endpoint,
        "health_url": sidecar_health_url(endpoint) if endpoint else "",
        "checks": [],
        "actions": [],
    }

    if not endpoint:
        return base_payload | {
            "ready": False,
            "status": "not_configured",
            "summary": "OCR sidecar 未配置",
            "details": ["缺少 EYEX_OCR_DOCUMENT_AI_URL。"],
            "actions": [
                {"label": "安装并配置 OCR", "command": ".\\install-ocr.cmd"},
                {"label": "启动完整应用", "command": ".\\start.cmd"},
            ],
        }

    health_url = sidecar_health_url(endpoint)
    getter = http_get_json or _http_get_json
    try:
        health_payload = getter(health_url, 0.8)
    except Exception as exc:
        return base_payload | {
            "ready": False,
            "status": "not_running",
            "summary": "OCR sidecar 未运行或无法连接",
            "details": [str(exc)],
            "actions": [
                {"label": "启动完整应用", "command": ".\\start.cmd"},
                {"label": "重新安装 OCR", "command": ".\\install-ocr.cmd"},
            ],
        }

    readiness = _normalize_sidecar_readiness(health_payload)
    contract_checks = _sidecar_contract_checks(profile, health_payload)
    checks = [*contract_checks, *readiness["checks"]]
    ready = bool(readiness["ready"]) and all(check.get("ready") is not False for check in contract_checks)
    if ready:
        return base_payload | {
            "ready": True,
            "status": "ready",
            "summary": "OCR 强准确链路已就绪",
            "details": [],
            "checks": checks,
            "actions": [],
            "sidecar": _sidecar_summary(health_payload),
        }

    problem_labels = _problem_stage_labels(checks)
    details = [check["reason"] for check in checks if check.get("reason")]
    return base_payload | {
        "ready": False,
        "status": "not_ready",
        "summary": f"OCR 强准确链路未就绪：{', '.join(problem_labels) if problem_labels else '依赖未就绪'}",
        "details": details,
        "checks": checks,
        "actions": _ocr_fix_actions(checks),
        "sidecar": _sidecar_summary(health_payload),
    }


def sidecar_health_url(extract_url: str) -> str:
    parsed = urlparse(extract_url)
    if not parsed.scheme or not parsed.netloc:
        return extract_url
    return urlunparse((parsed.scheme, parsed.netloc, "/health", "", "", ""))


def _http_get_json(url: str, timeout: float) -> dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _active_profile_payload() -> dict[str, Any]:
    try:
        return load_ocr_profile(settings.ocr_profile).model_dump()
    except Exception as exc:
        return {"profile_id": settings.ocr_profile, "load_error": str(exc)}


def _normalize_sidecar_readiness(health_payload: dict[str, Any]) -> dict[str, Any]:
    readiness = health_payload.get("strong_pipeline_readiness")
    if not isinstance(readiness, dict):
        ready = bool(health_payload.get("ok"))
        return {"ready": ready, "checks": []}

    stages = readiness.get("stages", {})
    checks: list[dict[str, Any]] = []
    if isinstance(stages, dict):
        for stage, status in stages.items():
            stage_status = status if isinstance(status, dict) else {}
            stage_ready = bool(stage_status.get("ready"))
            checks.append(
                {
                    "key": str(stage),
                    "label": _stage_label(str(stage)),
                    "ready": stage_ready,
                    "status": "ready" if stage_ready else "not_ready",
                    "engine_id": str(stage_status.get("engine_id") or ""),
                    "reason": str(stage_status.get("reason") or ""),
                }
            )
    return {"ready": bool(readiness.get("ready")), "checks": checks}


def _sidecar_contract_checks(profile: dict[str, Any], health_payload: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    contract_version = str(health_payload.get("api_contract_version") or "")
    if contract_version != SIDECAR_API_CONTRACT_VERSION:
        checks.append(
            {
                "key": "sidecar_api_contract",
                "label": "OCR sidecar API contract",
                "ready": False,
                "status": "restart_required",
                "engine_id": "",
                "reason": (
                    f"OCR sidecar is stale or incompatible: expected {SIDECAR_API_CONTRACT_VERSION}, "
                    f"got {contract_version or 'missing'}. Restart OCR sidecar with {SIDECAR_RESTART_COMMANDS}."
                ),
            }
        )

    expected_profile = str(profile.get("profile_id") or settings.ocr_profile)
    sidecar_profile_payload = health_payload.get("ocr_profile")
    sidecar_profile = (
        str(sidecar_profile_payload.get("profile_id") or "")
        if isinstance(sidecar_profile_payload, dict)
        else ""
    )
    if sidecar_profile and sidecar_profile != expected_profile:
        checks.append(
            {
                "key": "ocr_profile",
                "label": "OCR profile contract",
                "ready": False,
                "status": "not_ready",
                "engine_id": "",
                "reason": f"OCR profile mismatch: backend expects {expected_profile}, sidecar reports {sidecar_profile}.",
            }
        )

    expected_layout_policy = str(profile.get("merge_policy_version") or "")
    if expected_layout_policy == SIDECAR_LAYOUT_POLICY_VERSION:
        sidecar_layout_policy = (
            str(sidecar_profile_payload.get("merge_policy_version") or "")
            if isinstance(sidecar_profile_payload, dict)
            else ""
        )
        if sidecar_layout_policy != SIDECAR_LAYOUT_POLICY_VERSION:
            checks.append(
                {
                    "key": "layout_policy",
                    "label": "OCR canonical layout policy",
                    "ready": False,
                    "status": "restart_required",
                    "engine_id": "",
                    "reason": (
                        f"OCR sidecar is stale or missing layout policy support: expected "
                        f"{SIDECAR_LAYOUT_POLICY_VERSION}, got {sidecar_layout_policy or 'missing'}. "
                        f"Restart OCR sidecar with {SIDECAR_RESTART_COMMANDS}."
                    ),
                }
            )

    required = _required_gpu_accelerator(profile)
    if required:
        device = health_payload.get("device") if isinstance(health_payload.get("device"), dict) else {}
        resolved = str(device.get("resolved") or device.get("accelerator") or "").lower()
        current = str(device.get("current") or "").lower()
        available = [str(item).lower() for item in device.get("available_accelerators", [])] if isinstance(device.get("available_accelerators"), list) else []
        observed = {item for item in [resolved, current, *available] if item}
        if required not in observed:
            checks.append(
                {
                    "key": "gpu_accelerator",
                    "label": f"{required.upper()} accelerator contract",
                    "ready": False,
                    "status": "not_ready",
                    "engine_id": "",
                    "reason": f"OCR profile {expected_profile} requires {required}, but sidecar device reports {sorted(observed) or ['unknown']}.",
                }
            )
    return checks


def _required_gpu_accelerator(profile: dict[str, Any]) -> str | None:
    gpu_policy = profile.get("gpu_policy") if isinstance(profile.get("gpu_policy"), dict) else {}
    target = str(gpu_policy.get("target") or "").lower()
    default = str(gpu_policy.get("default_accelerator") or "").lower()
    if "nvidia" in target or default == "cuda":
        return "cuda"
    if "radeon" in target or "directml" in default:
        return "directml"
    return None


def _stage_label(stage: str) -> str:
    labels = {
        "paddleocr_vl": "已停用的 PaddleOCR-VL 阶段",
        "pp_structure_v3": "PP-StructureV3 表格/版面",
        "pp_ocr_v5": "PP-OCRv5 行级识别",
        "preprocess": "文档预处理",
        "merge": "DocumentIR 合并",
    }
    return labels.get(stage, stage)


def _problem_stage_labels(checks: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for check in checks:
        if check.get("ready"):
            continue
        labels.append(str(check.get("label") or check.get("key") or "未知依赖"))
    return labels


def _ocr_fix_actions(checks: list[dict[str, Any]]) -> list[dict[str, str]]:
    restart_required = any(check.get("status") == "restart_required" for check in checks)
    actions: list[dict[str, str]] = []
    if restart_required:
        actions.append({"label": "停止旧服务", "command": ".\\stop.cmd"})
    actions.append({"label": "启动完整应用", "command": ".\\start.cmd"})
    if checks:
        actions.append(
            {
                "label": "安装/配置 OCR 强链路",
                "command": ".\\install-ocr.cmd",
            }
        )
    deduped: list[dict[str, str]] = []
    seen_commands: set[str] = set()
    for action in actions:
        command = action["command"]
        if command in seen_commands:
            continue
        seen_commands.add(command)
        deduped.append(action)
    return deduped


def _sidecar_summary(health_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(health_payload.get("ok")),
        "api_contract_version": health_payload.get("api_contract_version"),
        "sidecar_build_id": health_payload.get("sidecar_build_id"),
        "profile_id": (health_payload.get("ocr_profile") or {}).get("profile_id")
        if isinstance(health_payload.get("ocr_profile"), dict)
        else None,
        "pipeline_stages": health_payload.get("pipeline_stages", []),
        "memory_protection": health_payload.get("memory_protection", {}),
        "device": health_payload.get("device", {}),
        "engines": health_payload.get("engines", []),
    }
