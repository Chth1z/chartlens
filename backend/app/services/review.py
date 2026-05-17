from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config_loader import load_extraction_schema
from app.core.database import FieldResultRecord, ReviewAuditRecord
from app.domain.models import DocumentIR, ReviewDecision, ValidatedFieldResult


def apply_review(record: FieldResultRecord, decision: ReviewDecision, db: Session) -> ValidatedFieldResult:
    schema = load_extraction_schema()
    field = schema.field_by_key(decision.field_key)
    if decision.normalized_code not in field.allowed_codes and not (
        "text" in field.allowed_codes and decision.normalized_code != "unknown"
    ):
        raise ValueError(f"Invalid code for {decision.field_key}: {decision.normalized_code}")

    current = ValidatedFieldResult.model_validate_json(record.payload_json)
    evidence_span = decision.evidence_span or current.evidence_span
    evidence_block_id = decision.evidence_block_id or current.evidence_block_id
    if (evidence_span and not evidence_block_id) or (evidence_block_id and not evidence_span):
        raise ValueError("Reviewed evidence requires both evidence_span and evidence_block_id")
    if decision.normalized_code != "unknown" and evidence_span and evidence_block_id:
        _validate_review_evidence(record, evidence_span, evidence_block_id)
    before_json = record.payload_json
    has_document_evidence = bool(evidence_span and evidence_block_id)
    provenance = {
        **current.provenance,
        "manual_review": True,
        "manual_review_without_document_evidence": decision.normalized_code != "unknown" and not has_document_evidence,
        "reviewer": decision.reviewer,
        "review_comment": decision.comment,
        "reviewed_at": decision.decided_at.isoformat(),
    }
    validator_messages = [
        message
        for message in current.validator_messages
        if message != "manual_review_without_document_evidence"
    ]
    if provenance["manual_review_without_document_evidence"]:
        validator_messages.append("manual_review_without_document_evidence")
    updated = current.model_copy(
        update={
            "raw_value": decision.raw_value or decision.normalized_code,
            "normalized_code": decision.normalized_code,
            "status": "confirmed" if decision.normalized_code != "unknown" else "unknown",
            "review_required": False,
            "auto_accepted": False,
            "confidence": 1.0 if decision.normalized_code != "unknown" else current.confidence,
            "evidence_span": evidence_span,
            "evidence_block_id": evidence_block_id,
            "reasoning_summary": f"人工复核确认：{decision.comment or ''}".strip(),
            "error_code": None,
            "validator_messages": validator_messages,
            "provenance": provenance,
            "validation_state": "reviewed",
            "risk_level": "medium" if provenance["manual_review_without_document_evidence"] else "low",
            "acceptance_reason": "manual_review",
        }
    )
    record.payload_json = updated.model_dump_json()
    record.reviewed = 1
    record.updated_at = datetime.now(timezone.utc)
    if record.case:
        record.case.updated_at = record.updated_at
    db.add(
        ReviewAuditRecord(
            case_id=record.case_id,
            field_key=record.field_key,
            before_json=before_json,
            after_json=record.payload_json,
            reviewer=decision.reviewer,
            comment=decision.comment,
            decided_at=decision.decided_at,
        )
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return updated


def _validate_review_evidence(record: FieldResultRecord, evidence_span: str, evidence_block_id: str) -> None:
    document_ir_json = record.case.document_ir_json if record.case else None
    if not document_ir_json:
        return
    document_ir = DocumentIR.model_validate(json.loads(document_ir_json))
    for block in document_ir.blocks:
        if block.block_id != evidence_block_id:
            continue
        if evidence_span not in block.text:
            raise ValueError("evidence_span was not found in the referenced DocumentIR block")
        return
    raise ValueError("evidence_block_id was not found in DocumentIR")
