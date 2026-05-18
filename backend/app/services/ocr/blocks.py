from __future__ import annotations

import hashlib
import re

from app.core.settings import settings
from app.domain.models import DocumentIRBlock, DocumentIRSection, DocumentProfile
from app.services.domain_profile import document_kind_for_section


SECTION_SPLIT = re.compile(r"(?P<label>[\u4e00-\u9fffA-Za-z0-9 -]{2,18})\s*[:：]")


def _blocks_from_text_pages(
    pages: list[tuple[int, str]],
    profile: DocumentProfile,
    *,
    source_engine: str = "pdf_text",
    source_page_kind: str = "native_pdf_text",
) -> list[DocumentIRBlock]:
    blocks: list[DocumentIRBlock] = []
    current_section = "未知"
    reading_order = 0
    for page, text in pages:
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        raw_parts = [part.strip() for part in re.split(r"\n{2,}", normalized_text) if part.strip()]
        if len(raw_parts) <= 1:
            raw_parts = [line.strip() for line in normalized_text.split("\n") if line.strip()]
        if not raw_parts and normalized_text.strip():
            raw_parts = [normalized_text.strip()]
        for raw in raw_parts:
            reading_order += 1
            section = _detect_section(raw, profile.section_aliases) or current_section
            current_section = section
            blocks.append(_make_text_block(raw, page, reading_order, section, source_engine, source_page_kind, profile))
    return blocks


def _make_text_block(
    text: str,
    page: int,
    reading_order: int,
    section: str,
    source_engine: str,
    source_page_kind: str,
    profile: DocumentProfile,
) -> DocumentIRBlock:
    block_id = f"b{reading_order:04d}-{hashlib.sha1(f'{page}:paragraph:{text}'.encode('utf-8')).hexdigest()[:8]}"
    return DocumentIRBlock(
        block_id=block_id,
        page=page,
        reading_order=reading_order,
        text=text,
        bbox=[],
        confidence=0.98 if text else 0.0,
        block_type="paragraph",
        section_id=_section_id(section),
        section_label=section,
        document_kind=document_kind_for_section(section, profile),
        source_engine=source_engine,
        source_page_kind=source_page_kind,
        ocr_profile=settings.ocr_profile,
        layout_profile="text_layout",
        quality_flags=[] if text else ["empty_text"],
        route_profile_id=settings.ocr_profile,
        accelerator="cpu",
        model_name="pdf_text" if source_engine == "pdf_text" else source_engine,
        engine_version=source_engine,
    )


def _renumber_blocks(blocks: list[DocumentIRBlock]) -> list[DocumentIRBlock]:
    ordered = sorted(blocks, key=lambda block: (block.page, block.reading_order, block.block_id))
    return [block.model_copy(update={"reading_order": index}) for index, block in enumerate(ordered, start=1)]


def _detect_section(text: str, aliases: dict[str, list[str]]) -> str | None:
    prefix = text[:40]
    for label, names in aliases.items():
        for alias in names:
            if prefix.startswith(alias) or re.match(rf"^\s*{re.escape(alias)}\s*[:：]", prefix):
                return label
    match = SECTION_SPLIT.match(prefix)
    if match:
        found = match.group("label").strip()
        for label, names in aliases.items():
            if found in names:
                return label
    return None


def _sections_from_blocks(blocks: list[DocumentIRBlock], aliases: dict[str, list[str]]) -> list[DocumentIRSection]:
    seen: dict[str, list[int]] = {}
    for block in blocks:
        seen.setdefault(block.section_label, []).append(block.page)
    return [
        DocumentIRSection(
            section_id=_section_id(label),
            label=label,
            aliases=aliases.get(label, []),
            page_range=sorted(set(pages)),
            confidence=0.9 if label != "未知" else 0.2,
        )
        for label, pages in seen.items()
    ]


def _section_id(label: str) -> str:
    return hashlib.sha1(label.encode("utf-8")).hexdigest()[:12]
