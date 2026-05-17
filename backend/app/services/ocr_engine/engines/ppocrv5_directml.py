"""PP-OCRv5 ONNX DirectML engine."""
from __future__ import annotations
import importlib.util
from pathlib import Path
from typing import Any
from app.core.settings import settings
from app.services.ocr_accelerators import _onnx_available_providers
from app.services.ocr_engine.types import IntelligentOcrBlock, IntelligentOcrResult
from app.services.ocr_engine.errors import directml_disabled_reason, disable_directml_for_process
from app.services.ocr_engine.engine_base import (
    ocr_engine_options, active_ocr_profile, engine_metadata,
)
from app.services.ocr_engine.preprocessing import iter_rapidocr_page_inputs
from app.services.ocr_engine.postprocessing import dedupe_ocr_blocks, offset_ocr_blocks, ocr_block_selection_score
from app.services.ocr_engine.payload_parse import blocks_from_rapidocr_output


def _positive_float(v, *, default):
    try: p = float(v)
    except Exception: return default
    return p if p > 0 else default

def _positive_int(v, *, default):
    try: p = int(v)
    except Exception: return default
    return p if p > 0 else default

def _positive_int_candidates(v, *, default):
    if isinstance(v, list): raw = v
    elif isinstance(v, str) and v.strip(): raw = [i.strip() for i in v.split(",")]
    else: raw = default
    cs = []
    for i in raw:
        p = _positive_int(i, default=0)
        if p > 0 and p not in cs: cs.append(p)
    return cs or default

def _truthy(v, *, default=False):
    if v is None: return default
    if isinstance(v, bool): return v
    return str(v).strip().lower() in {"1", "true", "yes", "on", "enabled"}

def _preprocess_modes_from_options(options):
    configured = options.get("image_preprocess_modes")
    if isinstance(configured, list):
        modes = [str(i).strip().lower() for i in configured if str(i).strip()]
    elif isinstance(configured, str) and configured.strip():
        modes = [i.strip().lower() for i in configured.split(",") if i.strip()]
    else:
        modes = [str(options.get("image_preprocess") or "none").strip().lower()]
    deduped = list(dict.fromkeys(m for m in modes if m))
    return deduped or ["none"]

def _directml_model_variant(options):
    v = str(options.get("model_type") or "server").strip().lower()
    if v not in {"mobile", "server"}:
        raise ValueError(f"Unsupported PP-OCRv5 DirectML model_type: {v}")
    return v

def _directml_model_files(variant):
    if variant == "server":
        return ("ch_PP-OCRv5_det_server.onnx", "ch_PP-OCRv5_rec_server.onnx")
    return ("ch_PP-OCRv5_det_mobile.onnx", "ch_PP-OCRv5_rec_mobile.onnx")


class PPOCRV5OnnxDirectMLEngine:
    name = "pp_ocr_v5_onnx_directml"

    def available(self):
        return self.unavailable_reason() == ""

    def unavailable_reason(self):
        dr = directml_disabled_reason()
        if dr: return dr
        options = ocr_engine_options(self.name)
        model_variant = _directml_model_variant(options)
        model_dir = settings.ocr_directml_model_dir
        if not model_dir: return "EYEX_OCR_DIRECTML_MODEL_DIR is not configured"
        if not Path(model_dir).exists(): return f"EYEX_OCR_DIRECTML_MODEL_DIR does not exist: {model_dir}"
        mp = Path(model_dir)
        missing = [n for n in _directml_model_files(model_variant) if not (mp / n).exists()]
        if missing: return f"EYEX_OCR_DIRECTML_MODEL_DIR is missing required PP-OCRv5 {model_variant} ONNX files: {', '.join(missing)}"
        providers = _onnx_available_providers()
        if "DmlExecutionProvider" not in providers:
            return f"ONNX Runtime DmlExecutionProvider is unavailable; providers={providers or ['none']}"
        if importlib.util.find_spec("rapidocr") is None:
            return "Python package 'rapidocr' is not installed for PP-OCRv5 ONNX execution"
        return ""

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        reason = self.unavailable_reason()
        if reason: raise RuntimeError(reason)
        import hashlib
        import logging
        import time
        from rapidocr import ModelType, OCRVersion, RapidOCR
        from app.services.ocr_engine.model_pool import get_or_create

        _log = logging.getLogger(__name__)

        options = ocr_engine_options(self.name)
        model_variant = _directml_model_variant(options)
        profile = active_ocr_profile()
        default_dpi = profile.render_dpi if profile and profile.render_dpi else 300
        render_dpi = _positive_int(options.get("render_dpi"), default=default_dpi)
        render_dpi_candidates = _positive_int_candidates(options.get("render_dpi_candidates"), default=[render_dpi])
        preprocess_modes = _preprocess_modes_from_options(options)
        safe = _truthy(options.get("directml_safe_mode"), default=True)
        tile_max = _positive_int(options.get("tile_max_side_len"), default=1536)
        tile_ov = _positive_int(options.get("tile_overlap"), default=96)
        page_render_workers = _positive_int(options.get("page_render_workers"), default=1)
        max_side_default = tile_max if safe else 4096
        max_side = _positive_int(options.get("rapidocr_max_side_len"), default=max_side_default)
        model_dir = Path(settings.ocr_directml_model_dir)
        params: dict[str, Any] = {
            "Global.model_root_dir": str(model_dir), "Global.max_side_len": max_side,
            "Global.log_level": str(options.get("log_level") or "warning"),
            "EngineConfig.onnxruntime.use_dml": True,
            "Det.ocr_version": OCRVersion.PPOCRV5, "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type": getattr(ModelType, model_variant.upper()),
            "Rec.model_type": getattr(ModelType, model_variant.upper()),
        }
        if "text_score" in options:
            params["Global.text_score"] = _positive_float(options.get("text_score"), default=0.5)
        if "det_limit_side_len" in options:
            params["Det.limit_side_len"] = _positive_int(options.get("det_limit_side_len"), default=736)
        if "det_limit_type" in options:
            params["Det.limit_type"] = str(options.get("det_limit_type") or "min")

        # Model singleton pool — avoids 1-3s ONNX init per request
        # Use str() on each value to avoid numpy/enum boolean comparison issues
        config_hash = hashlib.sha1(
            str(sorted((k, str(v)) for k, v in params.items())).encode()
        ).hexdigest()[:12]
        pool_key = f"rapidocr_dml_{model_variant}_{max_side}"

        # Freeze a copy of params for the factory closure — avoids shared mutable state
        frozen_params = dict(params)

        def _create_engine(_p=frozen_params):
            return RapidOCR(params=_p)

        try:
            engine = get_or_create(pool_key, _create_engine, config_hash=config_hash)
        except Exception as exc:
            disable_directml_for_process(exc)
            raise


        t_start = time.monotonic()
        selected_dpi = render_dpi_candidates[0]
        selected_scale = _positive_float(options.get("pdf_render_scale"), default=selected_dpi / 72.0)
        blocks: list[IntelligentOcrBlock] = []
        best_score = (-1, -1.0)
        candidate_metrics: list[dict[str, Any]] = []

        for cdpi in render_dpi_candidates:
            cscale = _positive_float(options.get("pdf_render_scale"), default=cdpi / 72.0)
            cblocks: list[IntelligentOcrBlock] = []
            tc = 0
            for pm in preprocess_modes:
                for pi in iter_rapidocr_page_inputs(file_path, render_scale=cscale,
                    preprocess_mode=pm, directml_safe_mode=safe,
                    tile_max_side_len=tile_max, tile_overlap=tile_ov,
                    page_render_workers=page_render_workers):
                    tc += 1
                    try:
                        output = engine(str(pi.image_path))
                    except Exception as exc:
                        disable_directml_for_process(exc)
                        raise
                    pb = blocks_from_rapidocr_output(output, page=pi.page)
                    cblocks.extend(offset_ocr_blocks(pb, offset_x=pi.offset_x, offset_y=pi.offset_y))
            cblocks = dedupe_ocr_blocks(cblocks)
            cscore = ocr_block_selection_score(cblocks)
            candidate_metrics.append({"render_dpi": cdpi, "preprocess_modes": preprocess_modes,
                "block_count": len(cblocks), "char_count": cscore[0],
                "avg_confidence": round(cscore[1], 4), "tile_count": tc, "selected": False})
            if cscore > best_score:
                best_score = cscore
                selected_dpi, selected_scale, blocks = cdpi, cscale, cblocks
        for m in candidate_metrics:
            m["selected"] = m["render_dpi"] == selected_dpi

        duration_ms = round((time.monotonic() - t_start) * 1000, 1)
        _log.info(
            "DirectML extract: %s → %d blocks, %.1f avg_conf, %.0fms",
            file_path.name, len(blocks), best_score[1], duration_ms,
        )

        return IntelligentOcrResult(engine=self.name, blocks=blocks, metadata={
            "ocr_raw_block_count": len(blocks), "model_variant": model_variant,
            "pdf_render_scale": selected_scale, "render_dpi": selected_dpi,
            "render_dpi_candidates": render_dpi_candidates, "ocr_candidate_metrics": candidate_metrics,
            "rapidocr_max_side_len": max_side, "directml_safe_mode": safe,
            "tile_max_side_len": tile_max, "tile_overlap": tile_ov,
            "image_preprocess": preprocess_modes[0], "image_preprocess_modes": preprocess_modes,
            "preprocess_profile": profile.preprocess_profile if profile else None,
            "extract_duration_ms": duration_ms,
            "page_render_workers": page_render_workers,
            "model_pool_key": pool_key,
            **engine_metadata("PP-OCRv5", "onnx-directml", accelerator="directml"),
        })
