from __future__ import annotations

import hashlib
import re

from app.domain.models import DocumentIRBlock, DocumentIRSection


def _detect_section(text: str, aliases: dict[str, list[str]]) -> str | None:
    prefix = _compact_text(text[:80])
    for label, names in aliases.items():
        for alias in names:
            compact_alias = _compact_text(alias)
            if not compact_alias:
                continue
            if prefix == compact_alias or prefix.startswith(f"{compact_alias}:") or prefix.startswith(f"{compact_alias}："):
                return label
    return None


def _standalone_key_label(text: str, labels: list[str]) -> str | None:
    compact = text.strip()
    for label in sorted(labels, key=len, reverse=True):
        if re.fullmatch(rf"{re.escape(label)}\s*[:：]", compact):
            return label
    return None


def _is_section_title_like(text: str, section: str, aliases: dict[str, list[str]]) -> bool:
    compact = _compact_text(text).strip(":：")
    names = [section, *aliases.get(section, [])]
    return any(compact == _compact_text(name) for name in names)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _section_id(section: str) -> str:
    digest = hashlib.sha1(section.encode("utf-8")).hexdigest()[:8]
    return f"section-{digest}"


def _sections_from_blocks(blocks: list[DocumentIRBlock]) -> list[DocumentIRSection]:
    seen: dict[str, list[int]] = {}
    for block in blocks:
        seen.setdefault(block.section_label, []).append(block.page)
    return [
        DocumentIRSection(
            section_id=_section_id(label),
            label=label,
            page_range=sorted(set(pages)),
            confidence=0.9 if label != "未知" else 0.3,
        )
        for label, pages in seen.items()
    ]


def _renumber_blocks(blocks: list[DocumentIRBlock]) -> list[DocumentIRBlock]:
    return [block.model_copy(update={"reading_order": index}) for index, block in enumerate(blocks, start=1)]
