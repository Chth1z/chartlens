from __future__ import annotations

import re

from app.domain.models import (
    DocumentIRBlock,
    DocumentProfile,
    LayoutNormalizationConfig,
    LayoutRegionRule,
)
from app.services.domain_profile import document_kind_for_section

from app.services.layout_normalizer.block_merging import (
    _key_label_start,
    _same_line_groups,
)
from app.services.layout_normalizer.sections import (
    _detect_section,
    _is_section_title_like,
    _section_id,
    _standalone_key_label,
)


LAYOUT_NORMALIZER_VERSION = "layout-normalizer-v1"


def _classify_blocks(
    blocks: list[DocumentIRBlock],
    profile: DocumentProfile,
    config: LayoutNormalizationConfig,
    split_patient_header_ids: set[str] | None = None,
) -> list[DocumentIRBlock]:
    normalized: list[DocumentIRBlock] = []
    current_section = "未知"
    split_patient_header_ids = split_patient_header_ids or set()
    for index, block in enumerate(blocks, start=1):
        section = _detect_section(block.text, profile.section_aliases)
        is_patient_header = _is_patient_header(block.text, config) or block.block_id in split_patient_header_ids
        if section:
            current_section = section
        elif is_patient_header:
            section = "基本信息"
        else:
            section = current_section

        block_type = block.block_type
        flags = list(block.quality_flags)
        if is_patient_header:
            block_type = "key_value"
            flags.append("layout_patient_header")
        elif section and _is_section_title_like(block.text, section, profile.section_aliases) and not _standalone_key_label(
            block.text,
            config.key_value_labels,
        ):
            block_type = "title"
        document_region, region_flag = _document_region(block, section, block_type, is_patient_header, config)
        if region_flag:
            flags.append(region_flag)

        normalized.append(
            block.model_copy(
                update={
                    "reading_order": index,
                    "block_type": block_type,
                    "section_id": _section_id(section),
                    "section_label": section,
                    "document_kind": document_kind_for_section(section, profile),
                    "document_region": document_region,
                    "layout_profile": LAYOUT_NORMALIZER_VERSION,
                    "quality_flags": list(dict.fromkeys(flags)),
                    "stage_source": "layout_normalization",
                }
            )
        )
    return normalized


def _split_patient_header_block_ids(blocks: list[DocumentIRBlock], config: LayoutNormalizationConfig) -> set[str]:
    labels = [label for label in config.patient_header_labels if label]
    if not labels:
        return set()
    header_ids: set[str] = set()
    for line in _same_line_groups(blocks, config.same_line_y_tolerance):
        label_count = sum(1 for block in line if _standalone_key_label(block.text, labels) or _key_label_start(block.text, labels))
        if label_count < config.patient_header_min_labels:
            continue
        header_ids.update(block.block_id for block in line)
    return header_ids


def _document_region(
    block: DocumentIRBlock,
    section: str,
    block_type: str,
    is_patient_header: bool,
    config: LayoutNormalizationConfig,
) -> tuple[str, str | None]:
    if is_patient_header:
        return config.patient_header_region, None
    if block_type == "title":
        return config.section_heading_region, None
    for rule in config.region_rules:
        if _region_rule_matches(rule, block, section, block_type):
            return rule.region, rule.quality_flag
    if section != "未知":
        return config.default_body_region, None
    return config.unknown_region, None


def _region_rule_matches(rule: LayoutRegionRule, block: DocumentIRBlock, section: str, block_type: str) -> bool:
    matched = False
    if rule.section_labels:
        if section not in rule.section_labels:
            return False
        matched = True
    if rule.block_types:
        if block_type not in rule.block_types:
            return False
        matched = True
    if rule.patterns:
        if not any(_safe_search(pattern, block.text) for pattern in rule.patterns):
            return False
        matched = True
    return matched


def _safe_search(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text) is not None
    except re.error:
        return False


def _is_patient_header(text: str, config: LayoutNormalizationConfig) -> bool:
    count = sum(1 for label in config.patient_header_labels if re.search(rf"{re.escape(label)}\s*[:：]", text))
    return count >= config.patient_header_min_labels
