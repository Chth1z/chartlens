from __future__ import annotations

from app.domain.clinical import DocumentFragment, EvidenceCandidate, OcrBlock
from app.domain.field_definitions import FieldDefinition


def compact_global_context_for_llm(
    blocks: list[OcrBlock] | list[DocumentFragment],
    *,
    budget: int,
    field: FieldDefinition | None = None,
) -> list[EvidenceCandidate]:
    context: list[EvidenceCandidate] = []
    remaining = budget
    for block in _rank_blocks_for_field(blocks, field):
        text = block.text.strip()
        if not text or remaining <= 0:
            continue
        prefix = f"[全局上下文 p.{block.page}] "
        allowed = remaining - len(prefix)
        if allowed <= 0:
            break
        if len(text) > allowed:
            text = text[: max(0, allowed - 3)] + "..."
        context.append(
            EvidenceCandidate(
                field_key="__global__",
                text=f"{prefix}{text}",
                page=block.page,
                bbox=block.bbox,
                ocr_confidence=block.confidence,
                score=0.35,
            )
        )
        remaining -= len(context[-1].text)
    return context


def build_llm_evidence_for_field(
    field: FieldDefinition,
    field_evidence: list[EvidenceCandidate],
    blocks: list[OcrBlock] | list[DocumentFragment],
) -> list[EvidenceCandidate]:
    compacted: list[EvidenceCandidate] = []
    remaining = field.llm.evidence_budget
    for item in field_evidence[: field.llm.max_evidence_items_for_llm]:
        if remaining <= 0:
            break
        text = item.text
        if len(text) > remaining:
            text = text[: max(0, remaining - 3)] + "..."
        compacted.append(item.model_copy(update={"text": text}))
        remaining -= len(text)

    if remaining >= 120:
        compacted.extend(compact_global_context_for_llm(blocks, budget=remaining, field=field))
    return compacted


def build_direct_evidence_for_llm(
    field: FieldDefinition,
    field_evidence: list[EvidenceCandidate],
    *,
    budget: int | None = None,
) -> list[EvidenceCandidate]:
    remaining = budget if budget is not None else min(field.llm.evidence_budget, field.evidence_window_chars * 2)
    compacted: list[EvidenceCandidate] = []
    for item in field_evidence[: field.max_evidence_items]:
        if remaining <= 0:
            break
        text = item.text.strip()
        if not text:
            continue
        if len(text) > remaining:
            text = text[: max(0, remaining - 3)] + "..."
        compacted.append(item.model_copy(update={"text": text}))
        remaining -= len(text)
    return compacted


def build_case_context_for_llm(
    blocks: list[OcrBlock] | list[DocumentFragment],
    *,
    fields: list[FieldDefinition],
    budget: int,
    per_section_limit: int = 3,
) -> list[EvidenceCandidate]:
    target_sections: list[str] = []
    for field in fields:
        target_sections.extend(field.source_sections)
        target_sections.extend(field.evidence_priority)
    target_sections.extend(["基本信息", "既往史", "个人史", "出院情况", "出院诊断", "手术记录"])
    target_sections = list(dict.fromkeys(section for section in target_sections if section))

    grouped: dict[str, list[DocumentFragment | OcrBlock]] = {}
    for block in blocks:
        section_name = str(getattr(block, "section_name", "OCR"))
        block_type = str(getattr(block, "block_type", "paragraph"))
        if block_type == "line":
            continue
        grouped.setdefault(section_name, []).append(block)

    ordered_blocks: list[DocumentFragment | OcrBlock] = []
    for section in target_sections:
        section_blocks = grouped.pop(section, [])
        ordered_blocks.extend(sorted(section_blocks, key=lambda item: (-item.confidence, item.page))[:per_section_limit])
    for section_blocks in grouped.values():
        ordered_blocks.extend(sorted(section_blocks, key=lambda item: (-item.confidence, item.page))[:1])

    context: list[EvidenceCandidate] = []
    remaining = budget
    seen: set[tuple[int, str]] = set()
    for block in ordered_blocks:
        if remaining <= 0:
            break
        text = block.text.strip()
        if not text:
            continue
        key = (block.page, text)
        if key in seen:
            continue
        seen.add(key)
        section_name = str(getattr(block, "section_name", "OCR"))
        prefix = f"[{section_name} p.{block.page}] "
        allowed = remaining - len(prefix)
        if allowed <= 0:
            break
        if len(text) > allowed:
            text = text[: max(0, allowed - 3)] + "..."
        candidate = EvidenceCandidate(
            field_key="__case_context__",
            text=f"{prefix}{text}",
            page=block.page,
            bbox=block.bbox,
            ocr_confidence=block.confidence,
            score=0.35,
        )
        context.append(candidate)
        remaining -= len(candidate.text)
    return context


def _rank_blocks_for_field(
    blocks: list[OcrBlock] | list[DocumentFragment],
    field: FieldDefinition | None,
) -> list[OcrBlock] | list[DocumentFragment]:
    if field is None:
        return blocks
    priority_terms = [
        field.label,
        *field.source_sections,
        *field.evidence_priority,
        *field.synonyms,
    ]
    priority_terms = [term for term in priority_terms if term]

    def score(item: tuple[int, OcrBlock]) -> tuple[int, float, int]:
        index, block = item
        text = block.text
        hits = sum(1 for term in priority_terms if term in text)
        return (hits, block.confidence, -index)

    ranked = sorted(enumerate(blocks), key=score, reverse=True)
    return [block for _, block in ranked]
