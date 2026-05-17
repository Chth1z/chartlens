from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.config_loader import load_ocr_evaluation_profile
from app.core.settings import settings
from app.services.ocr import build_document_ir
from app.services.ocr_accelerators import accelerator_probe
from app.services.ocr_engine.evaluation import evaluate_layout_tables, evaluate_page_level
from app.services.ocr_engine.observability import quality_band
from app.services.runtime_status import RuntimeJsonGetter, build_ocr_runtime_status


def run_ocr_evaluation_profile(profile_id: str, http_get_json: RuntimeJsonGetter | None = None) -> dict[str, Any]:
    profile = load_ocr_evaluation_profile(profile_id)
    profile_path = settings.config_dir / "ocr_evaluation_profiles" / f"{profile_id}.yaml"
    environment = _environment_report(profile, http_get_json=http_get_json)
    sidecar_preflight = environment.get("sidecar_preflight", {})
    if _profile_needs_sidecar_preflight(profile, profile_path) and _sidecar_preflight_blocks_eval(sidecar_preflight):
        return {
            "profile": _profile_payload(profile),
            "environment": environment,
            "summary": _sidecar_preflight_blocker_summary(sidecar_preflight),
            "cases": [],
        }
    if profile.thresholds.get("template"):
        case_results = []
        summary = _template_summary(profile.thresholds)
    else:
        case_results = [
            _evaluate_case(case, profile_path=profile_path, default_ocr_profile=profile.default_ocr_profile, default_document_profile=profile.default_document_profile)
            for case in profile.cases
        ]
        summary = _summarize_case_results(case_results, thresholds=profile.thresholds)
    return {
        "profile": _profile_payload(profile),
        "environment": environment,
        "summary": summary,
        "cases": case_results,
    }


def _profile_payload(profile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "label": profile.label,
        "default_ocr_profile": profile.default_ocr_profile,
        "default_document_profile": profile.default_document_profile,
        "thresholds": profile.thresholds,
    }


def _evaluate_case(case, *, profile_path: Path, default_ocr_profile: str | None, default_document_profile: str | None) -> dict[str, Any]:
    document_path = _resolve_document_path(profile_path, case.document_path)
    payload = document_path.read_bytes()
    ocr_profile_id = case.ocr_profile or default_ocr_profile or settings.ocr_profile
    document_profile_id = case.document_profile or default_document_profile or settings.document_profile

    with _override_setting("ocr_profile", ocr_profile_id):
        document_ir = build_document_ir(
            document_path,
            payload,
            document_id=case.case_id,
            profile_id=document_profile_id,
        )

    ocr_pages = _document_ir_pages(document_ir)
    eval_result = evaluate_page_level(ocr_pages, dict(case.truth_pages), document_id=case.case_id)
    layout_table_metrics = evaluate_layout_tables(document_ir, list(case.truth_blocks), list(case.truth_tables))
    layout_metrics = _layout_metrics_payload(layout_table_metrics)
    table_metrics = _table_metrics_payload(layout_table_metrics)
    metadata = document_ir.metadata
    first_block = document_ir.blocks[0] if document_ir.blocks else None
    resolved_engine = (
        (first_block.source_engine if first_block and first_block.source_engine else None)
        or metadata.get("ocr_engine")
        or metadata.get("ocr_adapter")
        or "none"
    )
    return {
        "case_id": case.case_id,
        "document_path": str(document_path),
        "ocr_profile": ocr_profile_id,
        "document_profile": document_profile_id,
        "ocr_engine": resolved_engine,
        "input_kind": metadata.get("input_kind", "unknown"),
        "cer": round(eval_result.cer, 4),
        "wer": round(eval_result.wer, 4),
        "quality_band": eval_result.quality_band,
        "block_count": len(document_ir.blocks),
        "char_count": eval_result.char_count,
        "truth_char_count": eval_result.truth_char_count,
        "layout_metrics": layout_metrics,
        "table_metrics": table_metrics,
        "page_results": eval_result.page_results,
        "ocr_page_quality": metadata.get("ocr_page_quality", []),
        "ocr_trace": metadata.get("ocr_trace", {}),
        "tags": list(case.tags),
    }


def _summarize_case_results(case_results: list[dict[str, Any]], *, thresholds: dict[str, float]) -> dict[str, Any]:
    total_cases = len(case_results)
    if thresholds.get("requires_real_hardware") and thresholds.get("requires_deidentified_corpus"):
        min_cases = int(thresholds.get("min_cases", 1))
        if total_cases < min_cases:
            return {
                "total_cases": total_cases,
                "passed_cases": 0,
                "failed_cases": max(min_cases - total_cases, 1),
                "avg_cer": None,
                "avg_wer": None,
                "quality_band": "blocked",
                "quality_counts": {},
                "thresholds": {
                    "max_cer": float(thresholds.get("max_cer", 0.05)),
                    "max_wer": float(thresholds.get("max_wer", 0.1)),
                    "min_cases": min_cases,
                    "target_accelerators": list(thresholds.get("target_accelerators", [])),
                },
                "hard_blocker": "missing_real_hardware_corpus",
                "blocker_message": (
                    "This OCR profile requires a de-identified real image/PDF corpus and a validated GPU route "
                    "before precision, layout, or hardware claims can be accepted."
                ),
            }
    total_truth_chars = sum(max(1, int(item.get("truth_char_count", 0))) for item in case_results)
    avg_cer = (
        sum(float(item.get("cer", 0.0)) * max(1, int(item.get("truth_char_count", 0))) for item in case_results) / total_truth_chars
        if total_truth_chars else 0.0
    )
    avg_wer = (
        sum(float(item.get("wer", 0.0)) * max(1, int(item.get("truth_char_count", 0))) for item in case_results) / total_truth_chars
        if total_truth_chars else 0.0
    )
    block_weight = sum(int(item.get("layout_metrics", {}).get("truth_block_count", 0) or 0) for item in case_results)
    table_weight = sum(int(item.get("table_metrics", {}).get("truth_table_cell_count", 0) or 0) for item in case_results)
    max_cer = float(thresholds.get("max_cer", 0.05))
    max_wer = float(thresholds.get("max_wer", 0.1))
    passed_cases = sum(1 for item in case_results if float(item.get("cer", 1.0)) <= max_cer and float(item.get("wer", 1.0)) <= max_wer)
    quality_counts: dict[str, int] = {}
    for item in case_results:
        band = str(item.get("quality_band") or "unknown")
        quality_counts[band] = quality_counts.get(band, 0) + 1
    return {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": total_cases - passed_cases,
        "avg_cer": round(avg_cer, 4),
        "avg_wer": round(avg_wer, 4),
        "avg_block_text_match_accuracy": _weighted_metric(case_results, "layout_metrics", "block_text_match_accuracy", "truth_block_count", block_weight),
        "avg_block_bbox_iou_accuracy": _weighted_metric(case_results, "layout_metrics", "block_bbox_iou_accuracy", "truth_block_count", block_weight),
        "avg_reading_order_accuracy": _weighted_metric(case_results, "layout_metrics", "reading_order_accuracy", "truth_block_count", block_weight),
        "avg_table_cell_text_accuracy": _weighted_metric(case_results, "table_metrics", "table_cell_text_accuracy", "truth_table_cell_count", table_weight),
        "avg_table_cell_key_accuracy": _weighted_metric(case_results, "table_metrics", "table_cell_key_accuracy", "truth_table_cell_count", table_weight),
        "avg_table_cell_bbox_accuracy": _weighted_metric(case_results, "table_metrics", "table_cell_bbox_accuracy", "truth_table_cell_count", table_weight),
        "quality_band": quality_band(1.0 - min(1.0, avg_cer)) if case_results else "unknown",
        "quality_counts": quality_counts,
        "thresholds": {"max_cer": max_cer, "max_wer": max_wer},
    }


def _layout_metrics_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "truth_block_count": metrics["truth_block_count"],
        "matched_block_count": metrics["matched_block_count"],
        "block_text_match_accuracy": metrics["block_text_match_accuracy"],
        "block_bbox_iou_accuracy": metrics["block_bbox_iou_accuracy"],
        "block_center_accuracy": metrics["block_center_accuracy"],
        "reading_order_accuracy": metrics["reading_order_accuracy"],
        "layout_match_details": metrics["layout_match_details"],
    }


def _table_metrics_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "truth_table_cell_count": metrics["truth_table_cell_count"],
        "matched_table_cell_count": metrics["matched_table_cell_count"],
        "table_cell_text_accuracy": metrics["table_cell_text_accuracy"],
        "table_cell_key_accuracy": metrics["table_cell_key_accuracy"],
        "table_cell_bbox_accuracy": metrics["table_cell_bbox_accuracy"],
        "table_match_details": metrics["table_match_details"],
    }


def _weighted_metric(case_results: list[dict[str, Any]], group: str, metric: str, weight_key: str, total_weight: int) -> float | None:
    if total_weight <= 0:
        return None
    score = 0.0
    for item in case_results:
        metrics = item.get(group, {})
        value = metrics.get(metric)
        if value is None:
            continue
        score += float(value) * int(metrics.get(weight_key, 0) or 0)
    return round(score / total_weight, 4)


def _template_summary(thresholds: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_cases": 0,
        "passed_cases": 0,
        "failed_cases": 0,
        "avg_cer": None,
        "avg_wer": None,
        "quality_band": "blocked",
        "quality_counts": {},
        "thresholds": {
            "max_cer": float(thresholds.get("max_cer", 0.05)),
            "max_wer": float(thresholds.get("max_wer", 0.1)),
            "target_accelerators": list(thresholds.get("target_accelerators", [])),
        },
        "template": True,
        "hard_blocker": "template_profile",
        "blocker_message": (
            "This OCR evaluation profile is a manifest template. Copy its case shape into a real "
            "profile with de-identified image/PDF fixtures before running precision evals."
        ),
    }


def _environment_report(profile, http_get_json: RuntimeJsonGetter | None = None) -> dict[str, Any]:
    target_accelerators = [str(item) for item in profile.thresholds.get("target_accelerators", [])]
    probes = accelerator_probe()
    return {
        "selected_profile": profile.profile_id,
        "default_ocr_profile": profile.default_ocr_profile or settings.ocr_profile,
        "target_accelerators": target_accelerators,
        "accelerator_probe": probes,
        "target_readiness": {
            accelerator: _target_readiness(accelerator, probes)
            for accelerator in target_accelerators
        },
        "run_commands": {
            "mock": ".\\scripts\\run-ocr-eval.ps1 -ProfileId mock_general",
            "hardware": f".\\scripts\\run-ocr-eval.ps1 -ProfileId {profile.profile_id}",
            "hardware_blocker_report": f".\\scripts\\run-ocr-eval.ps1 -ProfileId {profile.profile_id} -AllowEmptyHardwareProfile",
            "amd_probe": ".\\scripts\\probe-amd-ocr.ps1",
            "synthetic_directml_local_bypass": ".\\scripts\\run-ocr-eval.ps1 -ProfileId synthetic_medical_directml",
            "synthetic_directml_local_bypass_env": "$env:EYEX_OCR_DOCUMENT_AI_URL=''; .\\scripts\\run-ocr-eval.ps1 -ProfileId synthetic_medical_directml",
            "restart_stale_sidecar": ".\\stop.cmd; .\\start.cmd",
        },
        "sidecar_preflight": _sidecar_preflight(http_get_json=http_get_json),
    }


def _sidecar_preflight(http_get_json: RuntimeJsonGetter | None = None) -> dict[str, Any]:
    endpoint = settings.ocr_document_ai_url.strip() if settings.ocr_document_ai_url else ""
    if not endpoint:
        return {
            "configured": False,
            "ready": True,
            "status": "bypassed",
            "summary": "EYEX_OCR_DOCUMENT_AI_URL is empty; eval uses the in-process OCR route.",
            "actions": [],
        }
    status = build_ocr_runtime_status(http_get_json=http_get_json)
    return {
        "configured": True,
        "ready": bool(status.get("ready")),
        "status": status.get("status"),
        "summary": status.get("summary"),
        "details": status.get("details", []),
        "checks": status.get("checks", []),
        "actions": status.get("actions", []),
        "endpoint": status.get("endpoint"),
        "health_url": status.get("health_url"),
        "sidecar": status.get("sidecar", {}),
    }


def _sidecar_preflight_blocks_eval(preflight: dict[str, Any]) -> bool:
    if not preflight.get("configured"):
        return False
    if preflight.get("ready") is not True:
        return True
    checks = preflight.get("checks")
    if not isinstance(checks, list):
        checks = []
    blocking_keys = {"sidecar_api_contract", "layout_policy"}
    return any(
        isinstance(check, dict)
        and check.get("ready") is False
        and str(check.get("key") or "") in blocking_keys
        for check in checks
    )


def _profile_needs_sidecar_preflight(profile, profile_path: Path) -> bool:
    if profile.thresholds.get("template") or not profile.cases:
        return False
    for case in profile.cases:
        suffix = _resolve_document_path(profile_path, case.document_path).suffix.lower()
        if suffix not in {".txt", ".md"}:
            return True
    return False


def _sidecar_preflight_blocker_summary(preflight: dict[str, Any]) -> dict[str, Any]:
    summary = str(preflight.get("summary") or "Configured OCR sidecar failed eval preflight.")
    details = [str(item) for item in preflight.get("details", []) if str(item).strip()]
    message = " ".join([summary, *details]).strip()
    hard_blocker = (
        "stale_ocr_sidecar"
        if _sidecar_preflight_has_stale_contract_check(preflight)
        else "ocr_sidecar_preflight_failed"
    )
    return {
        "total_cases": 0,
        "passed_cases": 0,
        "failed_cases": 1,
        "avg_cer": None,
        "avg_wer": None,
        "quality_band": "blocked",
        "quality_counts": {},
        "hard_blocker": hard_blocker,
        "blocker_message": message,
        "restart_commands": [action.get("command") for action in preflight.get("actions", []) if isinstance(action, dict) and action.get("command")],
    }


def _sidecar_preflight_has_stale_contract_check(preflight: dict[str, Any]) -> bool:
    checks = preflight.get("checks")
    if not isinstance(checks, list):
        return False
    return any(
        isinstance(check, dict)
        and check.get("ready") is False
        and str(check.get("key") or "") in {"sidecar_api_contract", "layout_policy"}
        for check in checks
    )


def _target_readiness(accelerator: str, probes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    normalized = accelerator.lower()
    if normalized == "directml":
        probe = probes.get("directml", {})
        ready = bool(probe.get("available"))
        return {
            "profile_id": "windows_radeon_balanced",
            "ready": ready,
            "status": "ready" if ready else "not_ready",
            "evidence": {
                "provider_available": bool(probe.get("provider_available")),
                "providers": list(probe.get("providers", [])),
                "model_dir": str(probe.get("model_dir") or ""),
                "model_dir_exists": bool(probe.get("model_dir_exists")),
                "runtime_disabled_reason": str(probe.get("runtime_disabled_reason") or ""),
            },
        }
    if normalized == "cuda":
        probe = probes.get("cuda", {})
        return {
            "profile_id": "cuda_paddle",
            "ready": bool(probe.get("available")),
            "status": "ready" if probe.get("available") else "not_ready",
            "evidence": probe,
        }
    if normalized in {"rocm", "rocm_remote"}:
        rocm_probe = probes.get("rocm", {})
        remote_probe = probes.get("remote", {})
        ready = bool(remote_probe.get("available"))
        return {
            "profile_id": "rocm_remote_vl",
            "ready": ready,
            "status": "ready" if ready else "not_ready",
            "evidence": {
                "remote": remote_probe,
                "local_rocm": rocm_probe,
            },
        }
    probe = probes.get(normalized, {})
    return {
        "profile_id": "",
        "ready": bool(probe.get("available")),
        "status": "ready" if probe.get("available") else "not_ready",
        "evidence": probe,
    }


def _document_ir_pages(document_ir) -> dict[int, str]:
    pages: dict[int, list[tuple[int, str]]] = {}
    for block in sorted(document_ir.blocks, key=lambda item: (item.page, item.reading_order, item.block_id)):
        pages.setdefault(block.page, []).append((block.reading_order, block.text))
    return {
        page: "\n".join(text for _, text in blocks if text.strip())
        for page, blocks in pages.items()
    }


def _resolve_document_path(profile_path: Path, document_path: str) -> Path:
    raw = Path(document_path)
    resolved = raw if raw.is_absolute() else (profile_path.parent / raw).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"OCR evaluation document not found: {document_path}")
    return resolved


@contextmanager
def _override_setting(name: str, value: Any):
    original = getattr(settings, name)
    setattr(settings, name, value)
    try:
        yield
    finally:
        setattr(settings, name, original)
