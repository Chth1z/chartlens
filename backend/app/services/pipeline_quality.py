from __future__ import annotations

from app.domain.models import DocumentIR, ExtractionCandidate, ValidatedFieldResult
from app.services.llm_provider.types import SemanticExtractionProvider


def _quality_summary(results: list[ValidatedFieldResult], document_ir: DocumentIR) -> dict:
    non_unknown = [result for result in results if result.normalized_code not in (None, "unknown")]
    evidence_covered = [result for result in non_unknown if result.evidence_span and result.evidence_block_id]
    avg_confidence = (
        sum(float(block.confidence or 0) for block in document_ir.blocks) / len(document_ir.blocks)
        if document_ir.blocks
        else 0
    )
    metadata = document_ir.metadata or {}
    return {
        "field_count": len(results),
        "page_count": len({block.page for block in document_ir.blocks}) if document_ir.blocks else 0,
        "ocr_block_count": len(document_ir.blocks),
        "avg_ocr_confidence": avg_confidence,
        "low_confidence_block_count": len([block for block in document_ir.blocks if float(block.confidence or 0) < 0.75]),
        "quality_band": "good" if avg_confidence >= 0.9 else "fair" if avg_confidence >= 0.75 else "poor",
        "auto_accept_count": len([result for result in results if result.auto_accepted]),
        "review_required_count": len([result for result in results if result.review_required]),
        "unknown_count": len([result for result in results if result.normalized_code in (None, "unknown")]),
        "evidence_coverage": len(evidence_covered) / len(non_unknown) if non_unknown else 1.0,
        "input_kind": metadata.get("input_kind"),
        "ocr_adapter": metadata.get("ocr_adapter", "intelligent_document"),
        "ocr_engine": metadata.get("ocr_engine"),
        "ocr_intelligent_status": metadata.get("ocr_intelligent_status"),
        "ocr_attempted_engines": metadata.get("ocr_attempted_engines", []),
        "ocr_unavailable_engines": metadata.get("ocr_unavailable_engines", []),
        "ocr_unavailable_reasons": metadata.get("ocr_unavailable_reasons", {}),
        "ocr_engine_errors": metadata.get("ocr_engine_errors", {}),
        "ocr_trace": metadata.get("ocr_trace", {}),
        "ocr_page_quality": metadata.get("ocr_page_quality", []),
        "ocr_cache_status": metadata.get("ocr_cache_status"),
        "deidentification": metadata.get("deidentification", {}),
    }


def _page_quality_for_result(document_ir: DocumentIR, candidate: ExtractionCandidate) -> dict | None:
    page = candidate.page
    if page is None and candidate.evidence_block_id:
        for block in document_ir.blocks:
            if block.block_id == candidate.evidence_block_id:
                page = block.page
                break
    for item in document_ir.metadata.get("ocr_page_quality", []):
        if isinstance(item, dict) and item.get("page") == page:
            return item
    return None


def _provider_usage_value(provider: SemanticExtractionProvider, candidate: ExtractionCandidate, key: str):
    if candidate.provenance.get("route") == "skipped_no_evidence":
        return None
    return getattr(provider, "last_usage", {}).get(key)
