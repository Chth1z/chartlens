from __future__ import annotations

from app.domain.models import (
    DocumentContext,
    EvidenceCandidate,
    FieldDefinition,
)

from app.services.evidence_first.candidates import _dedupe_candidates
from app.services.evidence_first.rules import (
    _binary_history_evidence,
    _fact_then_code_evidence,
    _implicit_negative_evidence,
    _rule_pattern_evidence,
)


def collect_local_evidence(
    context: DocumentContext,
    fields: list[FieldDefinition],
) -> dict[str, list[EvidenceCandidate]]:
    from app.services.evidence_first.adjudication import _select_candidate

    evidence: dict[str, list[EvidenceCandidate]] = {field.key: [] for field in fields}
    blocks = [block for page in context.pages for block in page.blocks]
    for field in fields:
        candidates = []
        candidates.extend(_rule_pattern_evidence(field, blocks))
        candidates.extend(_fact_then_code_evidence(field, blocks))
        candidates.extend(_binary_history_evidence(field, blocks))
        candidates.extend(_implicit_negative_evidence(field, blocks))
        deduped = _dedupe_candidates(candidates)
        if deduped:
            selected = _select_candidate(field, deduped)
            evidence[field.key] = [selected, *[candidate for candidate in deduped if candidate != selected]]
        else:
            evidence[field.key] = []
    return evidence
