from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.clinical import OcrBlock
from app.domain.deidentify import deidentify_text
from app.application.document_fragments import FRAGMENT_PARSER_VERSION, build_document_fragments, summarize_ocr_quality
from app.application.evidence import retrieve_evidence
from app.application.implicit_negative import apply_implicit_negative
from app.application.layout_analysis import SECTION_CLASSIFIER_VERSION, fallback_regions_from_blocks
from app.application.llm_context import build_case_context_for_llm, build_direct_evidence_for_llm
from app.application.model_provider import HeuristicModelProvider, ModelProvider
from app.application.rule_extractor import extract_field_by_rules, should_escalate_to_llm
from app.infrastructure.db import models
from app.infrastructure.cache.processing_cache import (
    cache_key,
    llm_cache_key,
    load_cached_llm_results,
    load_cached_processing,
    save_cached_llm_results,
    save_cached_processing,
)
from app.infrastructure.config.field_dictionary import load_field_dictionary
from app.infrastructure.config.system_config import load_system_config
from app.infrastructure.db.session import SessionLocal
from app.infrastructure.model.openai_provider import build_model_provider
from app.infrastructure.ocr.engine import ocr_file
from app.infrastructure.ocr.postprocess import postprocess_ocr_blocks
from app.infrastructure.layout.provider import (
    build_layout_provider,
    layout_cache_key,
    load_cached_layout_regions,
    save_cached_layout_regions,
)
from app.core.config import settings


class SqlAlchemyCaseProcessor:
    def process_case(self, case_id: str) -> None:
        db = SessionLocal()
        try:
            case = db.scalar(select(models.CaseRecord).where(models.CaseRecord.case_id == case_id))
            if case is None:
                return
            path = Path(case.file_path)
            if not path.exists():
                case.status = "failed"
                case.error_message = "Original case file is missing"
                db.commit()
                return
            _process_case_impl(db=db, case=case, payload=path.read_bytes())
        finally:
            db.close()


def process_case(
    *,
    db: Session,
    case: models.CaseRecord,
    payload: bytes,
    provider: ModelProvider | None = None,
) -> models.CaseRecord:
    return _process_case_impl(db=db, case=case, payload=payload, provider=provider)


def _process_case_impl(
    *,
    db: Session,
    case: models.CaseRecord,
    payload: bytes,
    provider: ModelProvider | None = None,
) -> models.CaseRecord:
    dictionary = load_field_dictionary()
    system_config = load_system_config()
    ocr_profile = system_config.ocr.profile(settings.ocr_profile)
    provider = provider or build_model_provider()
    case.status = "processing"
    run = models.ProcessingRunRecord(
        run_id=f"RUN-{uuid4().hex[:12].upper()}",
        case_id=case.case_id,
        status="running",
        system_config_version=system_config.version,
        field_dictionary_version=dictionary.version,
        ocr_profile=settings.ocr_profile,
        layout_profile=settings.layout_profile,
        llm_profile=settings.model_mode,
    )
    db.add(run)
    db.commit()

    try:
        started_at = perf_counter()
        step_timings: dict[str, int | str | list[int] | dict[str, int]] = {}
        layout_profile = system_config.layout.profile(settings.layout_profile)
        layout_provider = build_layout_provider(layout_profile, ocr_profile_name=settings.ocr_profile)

        processing_cache_key = cache_key(
            file_hash=case.file_hash,
            ocr_profile_name=settings.ocr_profile,
            layout_profile_name=settings.layout_profile,
            ocr_profile=ocr_profile,
            fragment_parser_version=FRAGMENT_PARSER_VERSION,
            layout_provider=layout_provider.provider_name,
            layout_model=layout_provider.model_name,
            section_classifier_version=SECTION_CLASSIFIER_VERSION,
        )
        cached = load_cached_processing(processing_cache_key)
        if cached:
            raw_ocr_blocks, raw_fragments = cached
            step_timings["cache_hit"] = 1
            step_timings["ocr_ms"] = 0
            step_timings["fragment_ms"] = 0
            step_timings["layout_ms"] = 0
            step_timings["page_cache_hit_count"] = 0
            step_timings["page_cache_miss_count"] = 0
            step_timings["second_pass_ocr_pages"] = []
            step_timings["layout_provider"] = _layout_provider_from_fragments(raw_fragments, layout_provider.provider_name)
            step_timings["layout_region_count"] = _layout_region_count_from_fragments(raw_fragments)
            step_timings["layout_cache_hit_count"] = 0
            step_timings["section_classifier_version"] = SECTION_CLASSIFIER_VERSION
            step_timings["low_confidence_section_count"] = _low_confidence_section_count(raw_fragments)
            step_timings["reading_order_strategy"] = "layout_region"
        else:
            step_timings["cache_hit"] = 0
            case.status = "ocr"
            db.commit()
            step_started = perf_counter()
            page_cache_stats: dict[str, int | list[int]] = {}
            raw_ocr_blocks = postprocess_ocr_blocks(
                ocr_file(
                    Path(case.file_path),
                    payload,
                    ocr_profile=ocr_profile,
                    cache_namespace=case.file_hash,
                    cache_stats=page_cache_stats,
                )
            )
            step_timings["ocr_ms"] = _elapsed_ms(step_started)
            step_timings["page_cache_hit_count"] = page_cache_stats.get("page_cache_hit_count", 0)
            step_timings["page_cache_miss_count"] = page_cache_stats.get("page_cache_miss_count", 0)
            second_pass_pages = page_cache_stats.get("second_pass_ocr_pages", [])
            step_timings["second_pass_ocr_pages"] = second_pass_pages if isinstance(second_pass_pages, list) else []

            step_started = perf_counter()
            layout_regions, layout_metadata = _analyze_layout(
                case_path=Path(case.file_path),
                file_hash=case.file_hash,
                blocks=raw_ocr_blocks,
                provider=layout_provider,
            )
            step_timings["layout_ms"] = _elapsed_ms(step_started)
            step_timings.update(layout_metadata)

            step_started = perf_counter()
            raw_fragments = build_document_fragments(
                raw_ocr_blocks,
                section_aliases=layout_profile.section_aliases,
                layout_regions=layout_regions,
            )
            step_timings["low_confidence_section_count"] = _low_confidence_section_count(raw_fragments)
            step_timings["fragment_ms"] = _elapsed_ms(step_started)
            save_cached_processing(processing_cache_key, raw_ocr_blocks, raw_fragments)

        db.execute(delete(models.OcrBlockRecord).where(models.OcrBlockRecord.case_id == case.case_id))
        db.execute(delete(models.DocumentFragmentRecord).where(models.DocumentFragmentRecord.case_id == case.case_id))
        db.execute(delete(models.ExtractionResultRecord).where(models.ExtractionResultRecord.case_id == case.case_id))

        step_started = perf_counter()
        redacted_blocks: list[OcrBlock] = []
        for block in raw_ocr_blocks:
            redacted = deidentify_text(block.text)
            db.add(
                models.OcrBlockRecord(
                    case_id=case.case_id,
                    page=block.page,
                    text=block.text,
                    redacted_text=redacted.redacted_text,
                    bbox=block.bbox,
                    confidence=block.confidence,
                )
            )
            redacted_blocks.append(
                OcrBlock(
                    page=block.page,
                    text=redacted.redacted_text,
                    bbox=block.bbox,
                    confidence=block.confidence,
                )
            )

        redacted_fragments = []
        for fragment in raw_fragments:
            redacted = deidentify_text(fragment.text)
            redacted_fragment = fragment.model_copy(update={"text": redacted.redacted_text})
            redacted_fragments.append(redacted_fragment)
            db.add(
                models.DocumentFragmentRecord(
                    case_id=case.case_id,
                    page=fragment.page,
                    reading_order=fragment.reading_order,
                    text=fragment.text,
                    redacted_text=redacted.redacted_text,
                    bbox=fragment.bbox,
                    confidence=fragment.confidence,
                    section_name=fragment.section_name,
                    block_type=fragment.block_type,
                    source_kind=fragment.source_kind,
                    layout_region_id=fragment.layout_region_id,
                    layout_type=fragment.layout_type,
                    section_confidence=fragment.section_confidence,
                    parser_version=fragment.parser_version,
                )
            )
        step_timings["deidentify_ms"] = _elapsed_ms(step_started)

        quality = summarize_ocr_quality(raw_ocr_blocks, raw_fragments, low_confidence_threshold=ocr_profile.low_confidence_threshold)
        mvp_fields = [field for field in dictionary.fields if field.phase == 1]
        retrieval_fragments = [fragment for fragment in redacted_fragments if fragment.block_type != "line"]
        case.status = "extracting"
        db.commit()
        step_started = perf_counter()
        evidence_by_field = {
            field.key: retrieve_evidence(field, retrieval_fragments)
            for field in mvp_fields
        }
        step_timings["evidence_ms"] = _elapsed_ms(step_started)
        step_started = perf_counter()
        rule_results = {
            field.key: extract_field_by_rules(field, evidence_by_field.get(field.key, []))
            for field in mvp_fields
        }
        rule_results = {
            field.key: apply_implicit_negative(
                field,
                rule_results[field.key],
                retrieval_fragments,
                quality_band=quality.quality_band,
                history_terms=system_config.medical_dictionaries.history_fields,
                unknown_terms=system_config.medical_dictionaries.unknown_terms,
            )
            for field in mvp_fields
        }
        llm_fields = []
        llm_skipped_no_evidence_count = 0
        for field in mvp_fields:
            if not should_escalate_to_llm(field, rule_results[field.key]):
                continue
            if field.llm.skip_when_no_evidence and not evidence_by_field.get(field.key):
                llm_skipped_no_evidence_count += 1
                continue
            llm_fields.append(field)
        step_timings["rule_ms"] = _elapsed_ms(step_started)
        step_timings["llm_cache_hit"] = 0
        step_timings["llm_call_count"] = 0
        step_timings["llm_skipped_no_evidence_count"] = llm_skipped_no_evidence_count
        step_timings["llm_input_tokens_per_field"] = {}
        if llm_fields:
            step_started = perf_counter()
            provider_failed = False
            llm_profile = system_config.llm.profiles.get(settings.model_mode) or system_config.llm.profiles[system_config.llm.default_profile]
            for batch in _llm_field_batches(llm_fields, max_fields_per_call=llm_profile.max_fields_per_call):
                llm_evidence = {
                    field.key: build_direct_evidence_for_llm(field, evidence_by_field.get(field.key, []))
                    for field in batch
                }
                llm_evidence["__case_context__"] = build_case_context_for_llm(
                    retrieval_fragments,
                    fields=batch,
                    budget=settings.llm_case_context_budget,
                )
                field_keys = [field.key for field in batch]
                batch_cache_key = llm_cache_key(
                    fields=batch,
                    evidence_by_field=llm_evidence,
                    field_dictionary_version=dictionary.version,
                    system_config_version=system_config.version,
                    model=str(getattr(provider, "model", "")),
                    prompt_cache_key=llm_profile.prompt_cache_key,
                )
                cached_llm_results = load_cached_llm_results(batch_cache_key)
                if cached_llm_results is not None:
                    provider_results = cached_llm_results
                    provider_status = "cache_hit"
                    provider_error_code = None
                    step_timings["llm_cache_hit"] += 1
                    usage = _record_model_call(
                        db=db,
                        case_id=case.case_id,
                        provider=provider,
                        field_keys=field_keys,
                        latency_ms=0,
                        status=provider_status,
                        error_code=provider_error_code,
                        usage_override=_empty_usage(),
                    )
                else:
                    try:
                        provider_results = provider.extract_fields(
                            case_id=case.case_id,
                            fields=batch,
                            evidence_by_field=llm_evidence,
                        )
                        provider_status = "completed"
                        provider_error_code = None
                        step_timings["llm_call_count"] += 1
                        save_cached_llm_results(batch_cache_key, provider_results)
                    except Exception as exc:
                        provider_results = _fallback_model_results(
                            case_id=case.case_id,
                            fields=batch,
                            evidence_by_field=llm_evidence,
                            exc=exc,
                        )
                        provider_status = "failed"
                        provider_error_code = "PROVIDER_ERROR"
                        provider_failed = True
                    usage = _record_model_call(
                        db=db,
                        case_id=case.case_id,
                        provider=provider,
                        field_keys=field_keys,
                        latency_ms=0,
                        status=provider_status,
                        error_code=provider_error_code,
                    )
                for result in provider_results:
                    rule_results[result.field_key] = result
                run.input_tokens += int(usage.get("input_tokens", 0))
                run.output_tokens += int(usage.get("output_tokens", 0))
                run.cached_input_tokens += int(usage.get("cached_input_tokens", 0))
                run.cost_usd += float(usage.get("cost_usd", 0.0))
                _record_input_tokens_per_field(step_timings, field_keys, int(usage.get("input_tokens", 0)))
            step_timings["llm_ms"] = _elapsed_ms(step_started)

        results = [rule_results[field.key] for field in mvp_fields]

        for result in results:
            db.add(
                models.ExtractionResultRecord(
                    case_id=case.case_id,
                    field_key=result.field_key,
                    raw_value=result.raw_value,
                    normalized_code=result.normalized_code,
                    confidence=result.confidence,
                    evidence_text=result.evidence_text,
                    page=result.page,
                    bbox=result.bbox,
                    reasoning_summary=result.reasoning_summary,
                    review_required=result.review_required,
                    error_code=result.error_code,
                )
            )

        case.status = "degraded" if "provider_failed" in locals() and provider_failed else "processed"
        case.error_message = None
        run.status = "degraded" if case.status == "degraded" else "completed"
        run.parser_mode = "ocr"
        run.page_count = quality.page_count
        run.ocr_block_count = quality.ocr_block_count
        run.fragment_count = quality.fragment_count
        run.avg_ocr_confidence = quality.avg_ocr_confidence
        run.low_confidence_block_count = quality.low_confidence_block_count
        run.quality_band = quality.quality_band
        run.auto_accept_count = sum(1 for result in results if not result.review_required and result.normalized_code != "unknown")
        run.review_required_count = sum(1 for result in results if result.review_required)
        run.unknown_count = sum(1 for result in results if result.normalized_code in (None, "unknown"))
        run.latency_ms = _elapsed_ms(started_at)
        run.step_timings = step_timings
        run.completed_at = datetime.now(UTC)
    except Exception as exc:  # pragma: no cover - defensive pipeline guard
        case.status = "failed"
        case.error_message = str(exc)
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(case)
    return case


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def _record_model_call(
    *,
    db: Session,
    case_id: str,
    provider: ModelProvider,
    field_keys: list[str],
    latency_ms: int,
    status: str = "completed",
    error_code: str | None = None,
    usage_override: dict[str, int | float] | None = None,
) -> dict[str, int | float]:
    usage = usage_override if usage_override is not None else (getattr(provider, "last_usage", {}) or {})
    db.add(
        models.ModelCallLogRecord(
            call_id=f"LLM-{uuid4().hex[:12].upper()}",
            case_id=case_id,
            provider=provider.name,
            model=str(getattr(provider, "model", "")),
            mode=str(getattr(provider, "mode", settings.model_mode)),
            field_keys=field_keys,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
            cost_usd=float(usage.get("cost_usd", 0.0)),
            latency_ms=latency_ms,
            status=status,
            error_code=error_code,
        )
    )
    return {
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
        "cost_usd": float(usage.get("cost_usd", 0.0)),
    }


def _empty_usage() -> dict[str, int | float]:
    return {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "cost_usd": 0.0}


def _llm_field_batches(fields: list, *, max_fields_per_call: int) -> list[list]:
    grouped: dict[str, list] = {}
    for field in fields:
        grouped.setdefault(field.llm.prompt_profile, []).append(field)
    batches: list[list] = []
    batch_size = max(1, max_fields_per_call)
    for group_fields in grouped.values():
        for index in range(0, len(group_fields), batch_size):
            batches.append(group_fields[index : index + batch_size])
    return batches


def _record_input_tokens_per_field(
    step_timings: dict[str, int | str | list[int] | dict[str, int]],
    field_keys: list[str],
    input_tokens: int,
) -> None:
    if not field_keys:
        return
    per_field = step_timings.setdefault("llm_input_tokens_per_field", {})
    if not isinstance(per_field, dict):
        return
    share = int(input_tokens / len(field_keys)) if input_tokens else 0
    for field_key in field_keys:
        per_field[field_key] = int(per_field.get(field_key, 0)) + share


def _fallback_model_results(
    *,
    case_id: str,
    fields: list,
    evidence_by_field: dict,
    exc: Exception,
) -> list:
    fallback = HeuristicModelProvider()
    results = fallback.extract_fields(case_id=case_id, fields=fields, evidence_by_field=evidence_by_field)
    summary = _summarize_provider_error(exc)
    return [
        result.model_copy(
            update={
                "review_required": True,
                "reasoning_summary": f"在线模型调用失败，已回退本地规则：{summary}；{result.reasoning_summary}",
                "error_code": result.error_code or "MODEL_FALLBACK",
            }
        )
        for result in results
    ]


def _summarize_provider_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    return message[:180] if message else exc.__class__.__name__


def _analyze_layout(
    *,
    case_path: Path,
    file_hash: str,
    blocks: list[OcrBlock],
    provider,
) -> tuple[list, dict[str, int | str]]:
    page_images = _discover_page_images(case_path)
    metadata: dict[str, int | str] = {
        "layout_provider": provider.provider_name,
        "layout_model": provider.model_name,
        "layout_cache_hit_count": 0,
        "section_classifier_version": SECTION_CLASSIFIER_VERSION,
        "reading_order_strategy": "layout_region",
    }
    regions = []
    if page_images and provider.provider_name != "fallback_heuristic":
        key = layout_cache_key(
            file_hash=file_hash,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            parser_version=FRAGMENT_PARSER_VERSION,
            page_images=page_images,
        )
        cached_regions = load_cached_layout_regions(key)
        if cached_regions is not None:
            regions = cached_regions
            metadata["layout_cache_hit_count"] = 1
        else:
            try:
                regions = provider.analyze(page_images)
                save_cached_layout_regions(key, regions)
            except Exception:
                regions = []
                metadata["layout_provider"] = "fallback_heuristic"
                metadata["layout_model"] = "heuristic"
    if not regions:
        regions = fallback_regions_from_blocks(blocks)
        metadata["layout_provider"] = "fallback_heuristic"
        metadata["layout_model"] = "heuristic"
    metadata["layout_region_count"] = len(regions)
    return regions, metadata


def _discover_page_images(case_path: Path) -> list[Path]:
    suffix = case_path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"} and case_path.exists():
        return [case_path]
    if suffix == ".pdf":
        page_dir = case_path.parent / ".pages" / case_path.stem
        if page_dir.exists():
            return sorted(page_dir.glob("page_*.png"))
    return []


def _low_confidence_section_count(fragments: list) -> int:
    return sum(
        1
        for fragment in fragments
        if fragment.block_type != "line"
        and (fragment.section_name == "unknown_section" or getattr(fragment, "section_confidence", 1.0) < 0.50)
    )


def _layout_region_count_from_fragments(fragments: list) -> int:
    return len({fragment.layout_region_id for fragment in fragments if getattr(fragment, "layout_region_id", None)})


def _layout_provider_from_fragments(fragments: list, default: str) -> str:
    if any(getattr(fragment, "layout_region_id", "") and str(fragment.layout_region_id).startswith("pp-") for fragment in fragments):
        return "pp_structure_v3"
    if any(getattr(fragment, "layout_region_id", None) for fragment in fragments):
        return "fallback_heuristic"
    return default
