from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.pipeline import EvidenceCandidate, FieldExtractionResult
from app.services.field_dictionary import FieldDefinition
from app.services.rule_extractor import extract_field_by_rules


class ModelProvider(ABC):
    name: str

    @abstractmethod
    def extract_fields(
        self,
        *,
        case_id: str,
        fields: list[FieldDefinition],
        evidence_by_field: dict[str, list[EvidenceCandidate]],
    ) -> list[FieldExtractionResult]:
        raise NotImplementedError


class HeuristicModelProvider(ModelProvider):
    name = "local-heuristic-fallback"
    last_usage: dict[str, int | float] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    def extract_fields(
        self,
        *,
        case_id: str,
        fields: list[FieldDefinition],
        evidence_by_field: dict[str, list[EvidenceCandidate]],
    ) -> list[FieldExtractionResult]:
        del case_id
        results: list[FieldExtractionResult] = []
        for field in fields:
            evidence = evidence_by_field.get(field.key, [])
            result = extract_field_by_rules(field, evidence)
            results.append(
                result.model_copy(
                    update={
                        "reasoning_summary": f"本地规则 fallback：{result.reasoning_summary}",
                    }
                )
            )
        return results
