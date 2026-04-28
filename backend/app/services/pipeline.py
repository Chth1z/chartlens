from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import models
from app.schemas.pipeline import OcrBlock
from app.services.deidentify import deidentify_text
from app.services.document_fragments import build_document_fragments, summarize_ocr_quality
from app.services.evidence import retrieve_evidence
from app.services.field_dictionary import load_field_dictionary
from app.services.implicit_negative import apply_implicit_negative
from app.services.llm_context import build_case_context_for_llm, build_direct_evidence_for_llm
from app.services.model_provider import HeuristicModelProvider, ModelProvider
from app.services.ocr import ocr_file
from app.services.ocr_postprocess import postprocess_ocr_blocks
from app.services.openai_provider import build_model_provider
from app.services.processing_cache import cache_key, load_cached_processing, save_cached_processing
from app.services.rule_extractor import extract_field_by_rules, should_escalate_to_llm
from app.core.config import settings
from app.services.system_config import load_system_config


def process_case(
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
        ocr_profile=settings.ocr_profile,
        layout_profile=settings.layout_profile,
        llm_profile=settings.model_mode,
    )
    db.add(run)
    db.commit()

    try:
        started_at = perf_counter()
        step_timings: dict[str, int] = {}

        processing_cache_key = cache_key(
            file_hash=case.file_hash,
            ocr_profile_name=settings.ocr_profile,
            layout_profile_name=settings.layout_profile,
            ocr_profile=ocr_profile,
        )
        cached = load_cached_processing(processing_cache_key)
        if cached:
            raw_ocr_blocks, raw_fragments = cached
            step_timings["cache_hit"] = 1
            step_timings["ocr_ms"] = 0
            step_timings["fragment_ms"] = 0
        else:
            step_timings["cache_hit"] = 0
            case.status = "ocr"
            db.commit()
            step_started = perf_counter()
            raw_ocr_blocks = postprocess_ocr_blocks(ocr_file(Path(case.file_path), payload, ocr_profile=ocr_profile))
            step_timings["ocr_ms"] = _elapsed_ms(step_started)

            step_started = perf_counter()
            raw_fragments = build_document_fragments(raw_ocr_blocks)
            step_timings["fragment_ms"] = _elapsed_ms(step_started)
            save_cached_processing(processing_cache_key, raw_ocr_blocks, raw_fragments)

        db.execute(delete(models.OcrBlockRecord).where(models.OcrBlockRecord.case_id == case.case_id))
        db.execute(delete(models.DocumentFragmentRecord).where(models.DocumentFragmentRecord.case_id == case.case_id))
        db.execute(delete(models.ExtractionResultRecord).where(models.ExtractionResultRecord.case_id == case.case_id))

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
                )
            )

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
        rule_results = {
            field.key: extract_field_by_rules(field, evidence_by_field.get(field.key, []))
            for field in mvp_fields
        }
        rule_results = {
            field.key: apply_implicit_negative(field, rule_results[field.key], retrieval_fragments, quality_band=quality.quality_band)
            for field in mvp_fields
        }
        llm_fields = [
            field
            for field in mvp_fields
            if should_escalate_to_llm(field, rule_results[field.key])
        ]
        step_timings["rule_ms"] = _elapsed_ms(step_started)
        if llm_fields:
            step_started = perf_counter()
            llm_evidence = {
                field.key: build_direct_evidence_for_llm(field, evidence_by_field.get(field.key, []))
                for field in llm_fields
            }
            llm_evidence["__case_context__"] = build_case_context_for_llm(
                retrieval_fragments,
                fields=llm_fields,
                budget=settings.llm_case_context_budget,
            )
            try:
                provider_results = provider.extract_fields(
                    case_id=case.case_id,
                    fields=llm_fields,
                    evidence_by_field=llm_evidence,
                )
                provider_status = "completed"
                provider_error_code = None
            except Exception as exc:
                provider_results = _fallback_model_results(
                    case_id=case.case_id,
                    fields=llm_fields,
                    evidence_by_field=llm_evidence,
                    exc=exc,
                )
                provider_status = "failed"
                provider_error_code = "PROVIDER_ERROR"
            for result in provider_results:
                rule_results[result.field_key] = result
            step_timings["llm_ms"] = _elapsed_ms(step_started)
            usage = _record_model_call(
                db=db,
                case_id=case.case_id,
                provider=provider,
                field_keys=[field.key for field in llm_fields],
                latency_ms=step_timings["llm_ms"],
                status=provider_status,
                error_code=provider_error_code,
            )
            run.input_tokens += int(usage.get("input_tokens", 0))
            run.output_tokens += int(usage.get("output_tokens", 0))
            run.cached_input_tokens += int(usage.get("cached_input_tokens", 0))
            run.cost_usd += float(usage.get("cost_usd", 0.0))

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

        case.status = "degraded" if "provider_status" in locals() and provider_status == "failed" else "processed"
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
) -> dict[str, int | float]:
    usage = getattr(provider, "last_usage", {}) or {}
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
