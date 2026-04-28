from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.errors import NotFoundError
from app.domain.clinical import EvalRunRequest, FieldExtractionResult, ReviewUpdate, VisionFallbackRequest
from app.domain.system_config import SystemConfig
from app.infrastructure.db import models
from app.infrastructure.db.maintenance import delete_case_record_tree


class SqliteCaseRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_cases(self) -> list[dict]:
        records = self.db.scalars(select(models.CaseRecord).order_by(models.CaseRecord.created_at.desc())).all()
        return [self._case_payload(record) for record in records]

    def get_case(self, case_id: str) -> dict:
        return self._case_payload(self._case_or_raise(case_id))

    def case_exists_by_hash(self, file_hash: str) -> bool:
        return self.db.scalar(select(models.CaseRecord).where(models.CaseRecord.file_hash == file_hash).limit(1)) is not None

    def create_case(self, *, case_id: str, filename: str, file_hash: str, file_path: str) -> dict:
        record = models.CaseRecord(
            case_id=case_id,
            filename=filename,
            file_hash=file_hash,
            file_path=file_path,
            status="queued",
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._case_payload(record)

    def set_case_queued(self, case_id: str) -> None:
        record = self._case_or_raise(case_id)
        record.status = "queued"
        record.error_message = None
        self.db.commit()

    def get_case_file_path(self, case_id: str) -> Path:
        return Path(self._case_or_raise(case_id).file_path)

    def delete_case(self, case_id: str) -> int:
        self._case_or_raise(case_id)
        return delete_case_record_tree(self.db, case_id)

    def review_field(self, case_id: str, update: ReviewUpdate) -> dict:
        self._case_or_raise(case_id)
        result = self.db.scalar(
            select(models.ExtractionResultRecord).where(
                models.ExtractionResultRecord.case_id == case_id,
                models.ExtractionResultRecord.field_key == update.field_key,
            )
        )
        if result is None:
            result = models.ExtractionResultRecord(case_id=case_id, field_key=update.field_key)
            self.db.add(result)
            self.db.flush()

        audit = models.ReviewAuditRecord(
            case_id=case_id,
            field_key=update.field_key,
            old_raw_value=result.raw_value,
            old_normalized_code=result.normalized_code,
            new_raw_value=update.new_raw_value,
            new_normalized_code=update.new_normalized_code,
            reviewer=update.reviewer,
            reason=update.reason,
        )
        self.db.add(audit)

        result.raw_value = update.new_raw_value
        result.normalized_code = update.new_normalized_code
        result.review_required = False
        result.confidence = 1.0
        result.error_code = None
        result.reasoning_summary = f"人工复核：{update.reason}"
        result.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(result)
        return self._result_payload(result)

    def diagnostics(self, case_id: str, config: SystemConfig) -> dict:
        record = self._case_or_raise(case_id)
        runs = self.db.scalars(
            select(models.ProcessingRunRecord)
            .where(models.ProcessingRunRecord.case_id == case_id)
            .order_by(models.ProcessingRunRecord.created_at.desc())
        ).all()
        fragments = self.db.scalars(
            select(models.DocumentFragmentRecord)
            .where(models.DocumentFragmentRecord.case_id == case_id)
            .order_by(models.DocumentFragmentRecord.page, models.DocumentFragmentRecord.reading_order)
        ).all()
        model_calls = self.db.scalars(
            select(models.ModelCallLogRecord)
            .where(models.ModelCallLogRecord.case_id == case_id)
            .order_by(models.ModelCallLogRecord.created_at.desc())
        ).all()
        vision_requests = self.db.scalars(
            select(models.VisionFallbackRequestRecord)
            .where(models.VisionFallbackRequestRecord.case_id == case_id)
            .order_by(models.VisionFallbackRequestRecord.created_at.desc())
        ).all()
        latest_run = runs[0] if runs else None
        return {
            "case_id": record.case_id,
            "quality": self._quality_payload(latest_run),
            "latest_run": self._run_payload(latest_run) if latest_run else None,
            "run_count": len(runs),
            "runs": [self._run_payload(run) for run in runs[:10]],
            "fragments": [self._fragment_payload(fragment) for fragment in fragments if fragment.block_type != "line"][:300],
            "model_calls": [self._model_call_payload(call) for call in model_calls[:50]],
            "vision_requests": [self._vision_request_payload(item) for item in vision_requests[:50]],
            "config": {
                "ocr_default_profile": config.ocr.default_profile,
                "layout_default_profile": config.layout.default_profile,
                "llm_default_profile": config.llm.default_profile,
                "vision_fallback_enabled": config.llm.vision_fallback.enabled,
                "vision_fallback_requires_manual_approval": config.llm.vision_fallback.requires_manual_approval,
                "gold_sample_target_min": config.evaluation.gold_sample_target_min,
            },
        }

    def export_results(self, case_id: str) -> list[FieldExtractionResult]:
        self._case_or_raise(case_id)
        records = self.db.scalars(
            select(models.ExtractionResultRecord).where(models.ExtractionResultRecord.case_id == case_id)
        ).all()
        return [FieldExtractionResult.model_validate(self._result_payload(record)) for record in records]

    def create_eval_run(self, request: EvalRunRequest) -> dict:
        total = 0
        exact = 0
        unknown = 0
        review_required = 0
        auto_accept_total = 0
        auto_accept_exact = 0
        per_field: dict[str, dict[str, int]] = {}
        mismatches: list[dict] = []
        missing_cases: list[str] = []
        for item in request.cases:
            record = self.db.scalar(select(models.CaseRecord).where(models.CaseRecord.case_id == item.case_id))
            if record is None:
                missing_cases.append(item.case_id)
                continue
            results = {
                result.field_key: result
                for result in self.db.scalars(
                    select(models.ExtractionResultRecord).where(models.ExtractionResultRecord.case_id == item.case_id)
                ).all()
            }
            for field_key, expected in item.expected_fields.items():
                total += 1
                field_metrics = per_field.setdefault(
                    field_key,
                    {"total_fields": 0, "exact_matches": 0, "unknown_count": 0, "review_required_count": 0},
                )
                field_metrics["total_fields"] += 1
                actual = results.get(field_key)
                if actual is None or actual.normalized_code in (None, "unknown"):
                    unknown += 1
                    field_metrics["unknown_count"] += 1
                if actual is None or actual.review_required:
                    review_required += 1
                    field_metrics["review_required_count"] += 1
                if actual is not None and not actual.review_required:
                    auto_accept_total += 1
                matched = actual is not None and str(actual.normalized_code) == str(expected)
                if matched:
                    exact += 1
                    field_metrics["exact_matches"] += 1
                    if not actual.review_required:
                        auto_accept_exact += 1
                elif len(mismatches) < 50:
                    mismatches.append(
                        {
                            "case_id": item.case_id,
                            "field_key": field_key,
                            "expected": expected,
                            "actual": actual.normalized_code if actual is not None else None,
                            "review_required": True if actual is None else actual.review_required,
                            "evidence_text": actual.evidence_text if actual is not None else None,
                        }
                    )
        per_field_metrics = {
            field_key: {
                **values,
                "accuracy": round(values["exact_matches"] / values["total_fields"], 4) if values["total_fields"] else 0.0,
                "unknown_rate": round(values["unknown_count"] / values["total_fields"], 4) if values["total_fields"] else 0.0,
                "review_required_rate": (
                    round(values["review_required_count"] / values["total_fields"], 4) if values["total_fields"] else 0.0
                ),
            }
            for field_key, values in per_field.items()
        }
        metrics = {
            "total_fields": total,
            "exact_matches": exact,
            "accuracy": round(exact / total, 4) if total else 0.0,
            "unknown_rate": round(unknown / total, 4) if total else 0.0,
            "review_required_rate": round(review_required / total, 4) if total else 0.0,
            "auto_accept_accuracy": round(auto_accept_exact / auto_accept_total, 4) if auto_accept_total else 0.0,
            "per_field_metrics": per_field_metrics,
            "mismatches": mismatches,
            "missing_cases": missing_cases,
        }
        run = models.EvalRunRecord(
            eval_run_id=f"EVAL-{uuid4().hex[:12].upper()}",
            name=request.name,
            case_count=len(request.cases),
            metrics=metrics,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return {
            "eval_run_id": run.eval_run_id,
            "name": run.name,
            "case_count": run.case_count,
            "metrics": run.metrics,
            "created_at": run.created_at.isoformat(),
        }

    def create_vision_fallback_request(self, case_id: str, request: VisionFallbackRequest) -> dict:
        self._case_or_raise(case_id)
        record = models.VisionFallbackRequestRecord(
            request_id=f"VFR-{uuid4().hex[:12].upper()}",
            case_id=case_id,
            page=request.page,
            bbox=request.bbox,
            status="approved_pending",
            reason=request.reason,
            reviewer=request.reviewer,
            approved_at=datetime.now(UTC),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._vision_request_payload(record)

    def _case_or_raise(self, case_id: str) -> models.CaseRecord:
        record = self.db.scalar(select(models.CaseRecord).where(models.CaseRecord.case_id == case_id))
        if record is None:
            raise NotFoundError("Case not found")
        return record

    def _case_payload(self, record: models.CaseRecord) -> dict:
        results = self.db.scalars(
            select(models.ExtractionResultRecord).where(models.ExtractionResultRecord.case_id == record.case_id)
        ).all()
        blocks = self.db.scalars(select(models.OcrBlockRecord).where(models.OcrBlockRecord.case_id == record.case_id)).all()
        audits = self.db.scalars(select(models.ReviewAuditRecord).where(models.ReviewAuditRecord.case_id == record.case_id)).all()
        latest_run = self.db.scalar(
            select(models.ProcessingRunRecord)
            .where(models.ProcessingRunRecord.case_id == record.case_id)
            .order_by(models.ProcessingRunRecord.created_at.desc())
            .limit(1)
        )
        return {
            "case_id": record.case_id,
            "filename": record.filename,
            "file_hash": record.file_hash,
            "status": record.status,
            "error_message": record.error_message,
            "created_at": record.created_at.isoformat(),
            "results": [self._result_payload(result) for result in results],
            "ocr_blocks": [
                {
                    "page": block.page,
                    "text": block.redacted_text,
                    "bbox": block.bbox,
                    "confidence": block.confidence,
                }
                for block in blocks
            ],
            "audit_count": len(audits),
            "latest_run": self._run_payload(latest_run) if latest_run else None,
            "quality": self._quality_payload(latest_run),
        }

    @staticmethod
    def _result_payload(result: models.ExtractionResultRecord) -> dict:
        return {
            "field_key": result.field_key,
            "raw_value": result.raw_value,
            "normalized_code": result.normalized_code,
            "confidence": result.confidence,
            "evidence_text": result.evidence_text,
            "page": result.page,
            "bbox": result.bbox or [],
            "reasoning_summary": result.reasoning_summary,
            "review_required": result.review_required,
            "error_code": result.error_code,
        }

    @staticmethod
    def _run_payload(run: models.ProcessingRunRecord | None) -> dict | None:
        if run is None:
            return None
        return {
            "run_id": run.run_id,
            "status": run.status,
            "system_config_version": getattr(run, "system_config_version", ""),
            "field_dictionary_version": getattr(run, "field_dictionary_version", ""),
            "ocr_profile": run.ocr_profile,
            "layout_profile": run.layout_profile,
            "llm_profile": run.llm_profile,
            "parser_mode": run.parser_mode,
            "page_count": run.page_count,
            "ocr_block_count": run.ocr_block_count,
            "fragment_count": run.fragment_count,
            "avg_ocr_confidence": run.avg_ocr_confidence,
            "low_confidence_block_count": run.low_confidence_block_count,
            "quality_band": run.quality_band,
            "auto_accept_count": run.auto_accept_count,
            "review_required_count": run.review_required_count,
            "unknown_count": run.unknown_count,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "cached_input_tokens": getattr(run, "cached_input_tokens", 0),
            "cost_usd": run.cost_usd,
            "latency_ms": run.latency_ms,
            "step_timings": run.step_timings or {},
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    @staticmethod
    def _quality_payload(run: models.ProcessingRunRecord | None) -> dict:
        if run is None:
            return {
                "page_count": 0,
                "ocr_block_count": 0,
                "fragment_count": 0,
                "avg_ocr_confidence": 0.0,
                "low_confidence_block_count": 0,
                "quality_band": "poor",
                "needs_vision_fallback": False,
            }
        return {
            "page_count": run.page_count,
            "ocr_block_count": run.ocr_block_count,
            "fragment_count": run.fragment_count,
            "avg_ocr_confidence": run.avg_ocr_confidence,
            "low_confidence_block_count": run.low_confidence_block_count,
            "quality_band": run.quality_band,
            "needs_vision_fallback": run.quality_band == "poor",
        }

    @staticmethod
    def _fragment_payload(fragment: models.DocumentFragmentRecord) -> dict:
        return {
            "page": fragment.page,
            "reading_order": fragment.reading_order,
            "text": fragment.redacted_text,
            "bbox": fragment.bbox or [],
            "confidence": fragment.confidence,
            "section_name": fragment.section_name,
            "block_type": fragment.block_type,
            "source_kind": fragment.source_kind,
            "layout_region_id": getattr(fragment, "layout_region_id", None),
            "layout_type": getattr(fragment, "layout_type", None),
            "section_confidence": getattr(fragment, "section_confidence", 0.0),
            "parser_version": getattr(fragment, "parser_version", ""),
        }

    @staticmethod
    def _model_call_payload(call: models.ModelCallLogRecord) -> dict:
        return {
            "call_id": call.call_id,
            "provider": call.provider,
            "model": call.model,
            "mode": call.mode,
            "field_keys": call.field_keys or [],
            "input_tokens": call.input_tokens,
            "output_tokens": call.output_tokens,
            "cached_input_tokens": getattr(call, "cached_input_tokens", 0),
            "cost_usd": call.cost_usd,
            "latency_ms": call.latency_ms,
            "status": call.status,
            "error_code": call.error_code,
            "created_at": call.created_at.isoformat(),
        }

    @staticmethod
    def _vision_request_payload(record: models.VisionFallbackRequestRecord) -> dict:
        return {
            "request_id": record.request_id,
            "case_id": record.case_id,
            "page": record.page,
            "bbox": record.bbox or [],
            "status": record.status,
            "reason": record.reason,
            "reviewer": record.reviewer,
            "created_at": record.created_at.isoformat(),
            "approved_at": record.approved_at.isoformat() if record.approved_at else None,
        }
