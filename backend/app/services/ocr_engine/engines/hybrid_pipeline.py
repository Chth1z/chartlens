"""Hybrid OCR Pipeline engine — orchestrates multi-stage OCR."""
from __future__ import annotations
from pathlib import Path
from app.core.settings import settings
from app.services.ocr_engine.concurrency import run_with_timeout
from app.services.ocr_engine.errors import OcrErrorCode, OcrEngineError
from app.services.ocr_engine.types import IntelligentOcrResult
from app.services.ocr_engine.engine_base import (
    active_ocr_profile, ocr_stage_config, _engine_unavailable_reason,
    IntelligentOcrEngine,
)
from app.services.ocr_engine.canonicalize import (
    hybrid_required_model_stages, hybrid_execution_stages, merge_hybrid_ocr_results,
)


class PaddleOcrHybridPipelineEngine:
    name = "paddleocr_hybrid"

    def __init__(self, stage_registry=None):
        self._stage_registry = stage_registry

    def available(self):
        return self.unavailable_reason() == ""

    def unavailable_reason(self):
        profile = active_ocr_profile()
        if profile is None:
            return f"OCR profile '{settings.ocr_profile}' could not be loaded"
        reasons = []
        for stage in hybrid_required_model_stages(profile):
            engines = self._engines_for_stage(profile, stage)
            if not engines:
                reasons.append(f"{stage}: no engine configured")
                continue
            if not any(e.available() for e in engines):
                sr = [f"{e.name}: {_engine_unavailable_reason(e) or 'unavailable'}" for e in engines]
                reasons.append(f"{stage}: {'; '.join(sr)}")
        return "; ".join(reasons)

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        profile = active_ocr_profile()
        if profile is None:
            raise RuntimeError(f"OCR profile '{settings.ocr_profile}' could not be loaded")
        stage_results, stage_errors, stage_unavailable = {}, {}, {}
        for stage in hybrid_execution_stages(profile):
            engines = self._engines_for_stage(profile, stage)
            if not engines:
                stage_unavailable[stage] = "no engine configured"
                continue
            ee, eu = [], []
            for engine in engines:
                if not engine.available():
                    eu.append(f"{engine.name}: {_engine_unavailable_reason(engine) or 'unavailable'}")
                    continue
                try:
                    result = _extract_stage_with_timeout(profile, stage, engine, file_path)
                except Exception as exc:
                    ee.append(f"{engine.name}: {exc}")
                    continue
                if result.blocks:
                    stage_results[stage] = result
                    break
                ee.append(f"{engine.name}: engine returned no blocks")
            if stage not in stage_results:
                if eu: stage_unavailable[stage] = "; ".join(eu)
                if ee: stage_errors[stage] = "; ".join(ee)
        if not stage_results:
            raise RuntimeError(f"Hybrid OCR pipeline produced no stage results: {dict(**stage_unavailable, **stage_errors)}")
        return merge_hybrid_ocr_results(stage_results, profile=profile,
            stage_errors=stage_errors, stage_unavailable=stage_unavailable)

    def _engines_for_stage(self, profile, stage):
        sc = ocr_stage_config(profile, stage)
        eids = [str(sc.get("engine_id") or "").strip()]
        fb = sc.get("fallback_engine_ids", [])
        if isinstance(fb, list):
            eids.extend(str(i).strip() for i in fb)
        registry = self._stage_registry or _hybrid_stage_engine_registry()
        return [registry[eid] for eid in eids if eid and eid in registry]


def _extract_stage_with_timeout(profile, stage, engine, file_path: Path):
    timeout_seconds = _stage_timeout_seconds(profile, stage)
    if timeout_seconds <= 0:
        return engine.extract(file_path)
    try:
        return run_with_timeout(lambda path: engine.extract(path), file_path, timeout=timeout_seconds)
    except TimeoutError as exc:
        raise OcrEngineError(
            OcrErrorCode.PAGE_TIMEOUT,
            f"{stage} stage exceeded timeout of {timeout_seconds}s",
            engine_name=engine.name,
            stage=stage,
            recoverable=True,
        ) from exc


def _stage_timeout_seconds(profile, stage) -> float:
    sc = ocr_stage_config(profile, stage)
    for key in ("timeout_seconds", "document_timeout_seconds", "page_timeout_seconds"):
        value = sc.get(key)
        if value is None:
            options = sc.get("options") if isinstance(sc.get("options"), dict) else {}
            value = options.get(key)
        if value is None:
            continue
        try:
            parsed = float(value)
        except Exception:
            continue
        if parsed > 0:
            return parsed
    try:
        return max(0.0, float(settings.ocr_engine_timeout_seconds))
    except Exception:
        return 120.0


def _hybrid_stage_engine_registry():
    """Cached engine registry for hybrid pipeline stages.

    Must be a singleton: PPStructureV3/PaddleX crashes on re-initialization,
    and ONNX DirectML recompilation takes 1-3s per fresh instance.
    """
    global _HYBRID_STAGE_REGISTRY
    if _HYBRID_STAGE_REGISTRY is None:
        from app.services.ocr_engine.engines.paddleocr_vl import PaddleOCRVLEngine
        from app.services.ocr_engine.engines.paddle_structure_v3 import PaddleStructureV3Engine
        from app.services.ocr_engine.engines.ppocrv5_directml import PPOCRV5OnnxDirectMLEngine
        from app.services.ocr_engine.engines.ppocrv5_paddle import PPOCRV5PaddleEngine
        from app.services.ocr_engine.engines.http_document_ai import RemotePaddleOCRVLEngine
        _HYBRID_STAGE_REGISTRY = {
            "paddleocr_vl": PaddleOCRVLEngine(),
            "paddleocr_vl_remote": RemotePaddleOCRVLEngine(),
            "paddle_structure_v3": PaddleStructureV3Engine(),
            "pp_ocr_v5_onnx_directml": PPOCRV5OnnxDirectMLEngine(),
            "pp_ocr_v5_paddle": PPOCRV5PaddleEngine(),
        }
    return _HYBRID_STAGE_REGISTRY


_HYBRID_STAGE_REGISTRY: dict | None = None
