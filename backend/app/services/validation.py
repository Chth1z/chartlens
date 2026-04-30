from __future__ import annotations

from app.domain.models import DocumentIR, ExtractionCandidate, FieldDefinition, ValidatedFieldResult


COMPLEX_EXTRACT_MODES = {"fact_then_code", "computed_from_facts"}
LOW_OCR_CONFIDENCE = 0.75


def validate_candidate(
    candidate: ExtractionCandidate,
    field: FieldDefinition,
    document_ir: DocumentIR,
) -> ValidatedFieldResult:
    result = ValidatedFieldResult.model_validate(candidate.model_dump())
    messages = list(result.validator_messages)
    normalized = result.normalized_code or "unknown"

    if not _allowed_code(field, normalized):
        messages.append(f"normalized_code '{normalized}' is not allowed for {field.key}")
        result = _downgrade(result, "INVALID_CODE", messages)
        normalized = "unknown"

    if result.evidence_type == "no_evidence" and normalized != "unknown":
        messages.append("no_evidence results cannot carry a non-unknown normalized_code")
        result = _downgrade(result, "NO_EVIDENCE_VALUE", messages)
        normalized = "unknown"

    evidence_block = None
    if normalized != "unknown":
        if not result.evidence_span or not result.evidence_block_id:
            messages.append("non-unknown result requires evidence_span and evidence_block_id")
            result = _downgrade(result, "MISSING_EVIDENCE_SPAN", messages)
            normalized = "unknown"
        else:
            evidence_block = _block(document_ir, result.evidence_block_id)
            if evidence_block is None:
                messages.append("evidence_block_id was not found in DocumentIR")
                result = _downgrade(result, "EVIDENCE_BLOCK_NOT_FOUND", messages)
                normalized = "unknown"
            elif result.evidence_span not in evidence_block.text:
                messages.append("evidence_span was not found in the referenced DocumentIR block")
                result = _downgrade(result, "EVIDENCE_SPAN_NOT_FOUND", messages)
                normalized = "unknown"

    if (
        normalized != "unknown"
        and field.extract_mode in COMPLEX_EXTRACT_MODES
        and result.status != "derived_candidate"
        and result.evidence_type != "derived"
        and not result.facts
    ):
        messages.append("complex fact fields require extracted facts before coding")
        result = _review(result, "COMPLEX_FIELD_REQUIRES_FACTS", messages, risk_level="high")

    if normalized != "unknown" and evidence_block is not None and evidence_block.confidence < LOW_OCR_CONFIDENCE:
        messages.append("evidence block OCR confidence is below auto-accept threshold")
        result = _review(result, result.error_code or "LOW_OCR_CONFIDENCE", messages, risk_level="high")

    if result.evidence_type in {"inferred", "derived"} or result.status == "derived_candidate":
        messages.append("inferred or derived candidates cannot be auto-accepted")
        result = _review(result, result.error_code or "DERIVED_REQUIRES_REVIEW", messages, risk_level="high")

    if result.evidence_type == "conflict" or result.status == "conflict":
        messages.append("conflicting evidence requires review")
        result = _review(result, result.error_code or "CONFLICT", messages, risk_level="high")

    if normalized == "unknown":
        result = result.model_copy(
            update={
                "review_required": True,
                "auto_accepted": False,
                "validation_state": "rejected" if result.error_code and result.status == "error" else "needs_review",
                "risk_level": "high" if result.error_code else "medium",
                "acceptance_reason": result.acceptance_reason or "unknown_or_insufficient_evidence",
            }
        )
    else:
        auto_accepted = not result.review_required and result.confidence >= 0.85
        result = result.model_copy(
            update={
                "auto_accepted": auto_accepted,
                "validation_state": "accepted" if auto_accepted else "needs_review",
                "risk_level": result.risk_level if not auto_accepted else "low",
                "acceptance_reason": (
                    "high_confidence_evidence_validated" if auto_accepted else result.acceptance_reason or "requires_review"
                ),
            }
        )

    return result.model_copy(update={"validator_messages": messages})


def unknown_result(field: FieldDefinition, error_code: str, summary: str) -> ValidatedFieldResult:
    return ValidatedFieldResult(
        field_key=field.key,
        field_group_key=field.field_group_key,
        raw_value=None,
        normalized_code="unknown",
        status="not_mentioned",
        confidence=0.0,
        evidence_type="no_evidence",
        reasoning_summary=summary,
        review_required=True,
        error_code=error_code,
        auto_accepted=False,
        validation_state="needs_review",
        risk_level="medium",
        acceptance_reason="unknown_or_insufficient_evidence",
    )


def _allowed_code(field: FieldDefinition, normalized: str) -> bool:
    if normalized in field.allowed_codes:
        return True
    if "text" in field.allowed_codes and normalized != "unknown":
        return True
    if "integer" in field.allowed_codes and normalized.isdigit():
        return True
    if "duration" in field.allowed_codes and normalized != "unknown":
        return True
    return False


def _block(document_ir: DocumentIR, block_id: str):
    for block in document_ir.blocks:
        if block.block_id == block_id:
            return block
    return None


def _downgrade(result: ValidatedFieldResult, error_code: str, messages: list[str]) -> ValidatedFieldResult:
    return result.model_copy(
        update={
            "raw_value": None,
            "normalized_code": "unknown",
            "status": "error",
            "confidence": min(result.confidence, 0.3),
            "review_required": True,
            "error_code": error_code,
            "auto_accepted": False,
            "validator_messages": messages,
            "validation_state": "rejected",
            "risk_level": "critical",
            "acceptance_reason": error_code,
        }
    )


def _review(
    result: ValidatedFieldResult,
    error_code: str,
    messages: list[str],
    *,
    risk_level: str | None = None,
) -> ValidatedFieldResult:
    return result.model_copy(
        update={
            "review_required": True,
            "error_code": error_code,
            "auto_accepted": False,
            "validator_messages": messages,
            "validation_state": "needs_review",
            "risk_level": risk_level or result.risk_level,
            "acceptance_reason": error_code,
        }
    )
