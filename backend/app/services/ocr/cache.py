from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.core.config_loader import load_ocr_profile
from app.core.settings import settings
from app.domain.models import DocumentIRBlock
from app.services.ocr_engine import extract_with_intelligent_ocr


def _read_ocr_cache(payload: bytes, *, page: int, page_kind: str = "image_pdf_ocr") -> tuple[list[DocumentIRBlock], dict] | None:
    path = _ocr_cache_path(payload, page=page, engine_id=_route_cache_engine_id(page_kind), **_active_ocr_cache_dimensions())
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        blocks = [DocumentIRBlock.model_validate(item) for item in data.get("blocks", []) if isinstance(item, dict)]
        metadata = data.get("metadata", {})
    except Exception:
        return None
    if not blocks or not isinstance(metadata, dict):
        return None
    return blocks, metadata


def _write_ocr_cache(payload: bytes, blocks: list[DocumentIRBlock], metadata: dict, *, page: int, page_kind: str = "image_pdf_ocr") -> None:
    path = _ocr_cache_path(payload, page=page, engine_id=_route_cache_engine_id(page_kind), **_active_ocr_cache_dimensions())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"blocks": [block.model_dump() for block in blocks], "metadata": metadata},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _ocr_cache_path(
    payload: bytes,
    *,
    page: int,
    page_image_hash: str | None = None,
    ocr_profile_id: str | None = None,
    ocr_profile_version: str | None = None,
    engine_id: str | None = None,
    engine_version: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    accelerator: str | None = None,
    render_dpi: int | None = None,
    preprocess_profile: str | None = None,
    stage: str | None = None,
    merge_policy_version: str | None = None,
    ocr_options_fingerprint: str | None = None,
    layout_profile: str = "intelligent_document",
) -> Path:
    payload_sha = hashlib.sha256(payload).hexdigest()
    cache_key = hashlib.sha256(
        (
            f"{payload_sha}:{page}:{page_image_hash or payload_sha}:"
            f"{ocr_profile_id or settings.ocr_profile}:{ocr_profile_version or 'default'}:{engine_id or 'profile_route'}:"
            f"{engine_version or 'default'}:{model_name or 'default'}:{model_version or 'default'}:"
            f"{accelerator or settings.ocr_accelerator}:{render_dpi or 'default'}:"
            f"{preprocess_profile or 'default'}:{stage or 'default'}:{merge_policy_version or 'default'}:"
            f"{ocr_options_fingerprint or 'default'}:"
            f"{layout_profile}:{settings.ocr_route_version}:{settings.ocr_strategy}:"
            f"{_ocr_extractor_cache_fingerprint()}"
        ).encode("utf-8")
    ).hexdigest()
    return settings.storage_dir / "ocr_cache" / f"{cache_key}.json"


def _route_cache_engine_id(page_kind: str) -> str:
    try:
        from app.services.ocr_engine.engine_base import _engine_names_for_page_kind

        names = _engine_names_for_page_kind(page_kind)
    except Exception:
        names = []
    return f"route:{page_kind}:{','.join(names)}" if names else f"route:{page_kind}"


def _active_ocr_cache_dimensions() -> dict:
    try:
        profile = load_ocr_profile(settings.ocr_profile)
    except Exception:
        return {}
    return {
        "ocr_profile_version": profile.version,
        "render_dpi": profile.render_dpi,
        "preprocess_profile": profile.preprocess_profile,
        "merge_policy_version": profile.merge_policy_version,
        "ocr_options_fingerprint": _ocr_profile_options_fingerprint(profile),
    }


def _ocr_profile_options_fingerprint(profile) -> str:
    relevant = {
        "pipeline_stages": profile.pipeline_stages,
        "stage_models": profile.stage_models,
        "cache_policy": profile.cache_policy,
    }
    encoded = json.dumps(relevant, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _ocr_extractor_cache_fingerprint() -> str:
    from app.services.ocr_engine.canonicalize import CANONICAL_LAYOUT_VERSION
    from app.services import ocr as _pkg

    func = _pkg.extract_with_intelligent_ocr
    module = getattr(func, "__module__", "unknown")
    qualname = getattr(func, "__qualname__", "unknown")
    return f"{module}.{qualname}:{CANONICAL_LAYOUT_VERSION}"


def _with_cache_status(metadata: dict, status: str) -> dict:
    updated = {**metadata, "ocr_cache_status": status}
    page_quality = []
    for item in metadata.get("ocr_page_quality", []):
        if isinstance(item, dict):
            page_quality.append({**item, "cache_status": status})
    if page_quality:
        updated["ocr_page_quality"] = page_quality
    return updated


def _combined_cache_status(metadata_items) -> str:
    statuses = [item.get("ocr_cache_status") for item in metadata_items if isinstance(item, dict)]
    if statuses and all(status == "hit" for status in statuses):
        return "hit"
    if statuses and any(status == "hit" for status in statuses):
        return "partial"
    if statuses and all(status == "miss" for status in statuses):
        return "miss"
    return "not_applicable"
