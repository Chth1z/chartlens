from abc import ABC, abstractmethod
from typing import Any
from app.domain.models import DocumentIR, DocumentContext, DocumentIRBlock, EvidenceCandidate, ExtractionCandidate, FieldDecision, FieldDefinition, FieldGroup

class SemanticExtractionProvider(ABC):
    name = "semantic-provider"
    route = "unknown"
    last_usage: dict[str, Any] = {}

    @abstractmethod
    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        raise NotImplementedError

    def collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        from app.services.evidence_first import collect_local_evidence

        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "cost_usd": 0.0}
        return collect_local_evidence(document_context, fields)

    def adjudicate_fields(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
        evidence_by_field: dict[str, list[EvidenceCandidate]],
    ) -> dict[str, FieldDecision]:
        del document_context
        from app.services.evidence_first import adjudicate_field_decisions

        return adjudicate_field_decisions(fields, evidence_by_field)

    def verify_against_document(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
        decisions_by_field: dict[str, FieldDecision],
    ) -> dict[str, FieldDecision]:
        del document_context, fields
        return decisions_by_field


def _unknown_model_unavailable(field: FieldDefinition, error_code: str, summary: str) -> ExtractionCandidate:
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="unknown",
        status="error",
        confidence=0.0,
        evidence_type="no_evidence",
        reasoning_summary=summary,
        review_required=True,
        error_code=error_code,
        provenance={"source": "model_fallback"},
        acceptance_reason=error_code,
        risk_level="high",
        validation_state="needs_review",
    )

