from __future__ import annotations

import hashlib
import re

from app.domain.models import (
    DocumentIR,
    DocumentIRBlock,
    DocumentIRSection,
    DocumentProfile,
    LayoutNormalizationConfig,
    LayoutRegionRule,
)
from app.services.domain_profile import document_kind_for_section


LAYOUT_NORMALIZER_VERSION = "layout-normalizer-v1"


def normalize_document_layout(document_ir: DocumentIR, profile: DocumentProfile) -> DocumentIR:
    config = profile.layout_normalization
    if not config.enabled:
        return document_ir

    kept: list[DocumentIRBlock] = []
    removed_count = 0
    for block in document_ir.blocks:
        if config.remove_screen_chrome and _is_screen_chrome(block.text, config):
            removed_count += 1
            continue
        kept.append(block)

    ordered = sorted(kept, key=_layout_sort_key)
    merged_blocks, merged_count = _merge_same_line_blocks(ordered, config) if config.merge_same_line_fragments else (ordered, 0)
    split_patient_header_ids = _split_patient_header_block_ids(merged_blocks, config)
    paragraph_blocks, paragraph_count = _merge_wrapped_paragraph_blocks(merged_blocks, config)
    normalized_blocks = _classify_blocks(paragraph_blocks, profile, config, split_patient_header_ids)
    if config.derive_key_value_blocks:
        output_blocks, derived_count, neighbor_derived_count = _derive_key_value_blocks(normalized_blocks, config)
    else:
        output_blocks = _renumber_blocks(normalized_blocks)
        derived_count = 0
        neighbor_derived_count = 0

    metadata = {
        **document_ir.metadata,
        "layout_normalization": {
            "version": LAYOUT_NORMALIZER_VERSION,
            "enabled": True,
            "input_blocks": len(document_ir.blocks),
            "output_blocks": len(output_blocks),
            "removed_screen_chrome_blocks": removed_count,
            "merged_same_line_fragments": merged_count,
            "merged_wrapped_paragraphs": paragraph_count,
            "derived_key_value_blocks": derived_count,
            "derived_neighbor_key_value_blocks": neighbor_derived_count,
        },
    }
    return document_ir.model_copy(
        update={
            "blocks": output_blocks,
            "sections": _sections_from_blocks(output_blocks),
            "metadata": metadata,
        }
    )


def _is_screen_chrome(text: str, config: LayoutNormalizationConfig) -> bool:
    compact = text.strip()
    if not compact:
        return False
    for pattern in config.screen_chrome_patterns:
        try:
            if re.search(pattern, compact):
                return True
        except re.error:
            continue
    return False


def _layout_sort_key(block: DocumentIRBlock) -> tuple[int, float, float, int, str]:
    if len(block.bbox) >= 4:
        return (block.page, float(block.bbox[1]), float(block.bbox[0]), block.reading_order, block.block_id)
    return (block.page, float(block.reading_order) * 10000.0, 0.0, block.reading_order, block.block_id)


def _same_line_groups(blocks: list[DocumentIRBlock], y_tolerance: float) -> list[list[DocumentIRBlock]]:
    groups: list[list[DocumentIRBlock]] = []
    current: list[DocumentIRBlock] = []
    current_page: int | None = None
    current_y: float | None = None
    for block in sorted(blocks, key=_layout_sort_key):
        if len(block.bbox) < 4:
            if current:
                groups.append(current)
                current = []
                current_page = None
                current_y = None
            groups.append([block])
            continue
        y = float(block.bbox[1])
        if current and current_page == block.page and current_y is not None and abs(y - current_y) <= y_tolerance:
            current.append(block)
            current_y = sum(float(item.bbox[1]) for item in current if len(item.bbox) >= 4) / max(1, len(current))
            continue
        if current:
            groups.append(current)
        current = [block]
        current_page = block.page
        current_y = y
    if current:
        groups.append(current)
    return groups


def _merge_same_line_blocks(
    blocks: list[DocumentIRBlock],
    config: LayoutNormalizationConfig,
) -> tuple[list[DocumentIRBlock], int]:
    merged: list[DocumentIRBlock] = []
    merge_count = 0
    for block in blocks:
        if merged and _can_merge_same_line(merged[-1], block, config):
            merged[-1] = _merge_blocks(merged[-1], block)
            merge_count += 1
            continue
        merged.append(block)
    return merged, merge_count


def _merge_wrapped_paragraph_blocks(
    blocks: list[DocumentIRBlock],
    config: LayoutNormalizationConfig,
) -> tuple[list[DocumentIRBlock], int]:
    merged: list[DocumentIRBlock] = []
    count = 0
    index = 0
    ordered = sorted(blocks, key=_layout_sort_key)
    while index < len(ordered):
        block = ordered[index]
        group = [block]
        cursor = index + 1
        while cursor < len(ordered) and _can_merge_wrapped_paragraph(group[-1], ordered[cursor], config):
            group.append(ordered[cursor])
            cursor += 1
        if len(group) > 1:
            merged.append(_merge_paragraph_group(group))
            count += len(group) - 1
            index = cursor
            continue
        merged.append(block)
        index += 1
    return merged, count


def _can_merge_wrapped_paragraph(left: DocumentIRBlock, right: DocumentIRBlock, config: LayoutNormalizationConfig) -> bool:
    if left.page != right.page or len(left.bbox) < 4 or len(right.bbox) < 4:
        return False
    if left.table_id or right.table_id or left.block_type == "cell" or right.block_type == "cell":
        return False
    if _starts_independent_field_label(left.text, config) or _starts_independent_field_label(right.text, config):
        return False
    if _is_screen_chrome(left.text, config) or _is_screen_chrome(right.text, config):
        return False
    if _looks_like_section_heading(left.text) or _looks_like_section_heading(right.text):
        return False
    left_x1, left_y1, left_x2, left_y2 = [float(value) for value in left.bbox[:4]]
    right_x1, right_y1, _, right_y2 = [float(value) for value in right.bbox[:4]]
    line_gap = right_y1 - left_y2
    if line_gap < -config.same_line_y_tolerance or line_gap > max(42.0, config.same_line_y_tolerance * 3):
        return False
    if abs(right_x1 - left_x1) > max(36.0, config.merge_horizontal_gap):
        return False
    left_text = left.text.strip()
    right_text = right.text.strip()
    if not left_text or not right_text:
        return False
    if re.search(r"[。；;!?！？]\s*$", left_text):
        return _is_short_continuation(right_text, right_y2 - right_y1)
    return True


def _looks_like_section_heading(text: str) -> bool:
    compact = _compact_text(text).strip()
    if not compact:
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9（）()·\-]{1,18}[:：]?", compact) and compact.endswith((":", "：")))


def _is_short_continuation(text: str, line_height: float) -> bool:
    del line_height
    return len(text) <= 32 and not re.search(r"[:：]\s*$", text)


def _merge_paragraph_group(blocks: list[DocumentIRBlock]) -> DocumentIRBlock:
    text = "".join(block.text.strip() for block in blocks)
    block_id = "+".join(block.block_id for block in blocks)
    bbox = _union_many([block.bbox for block in blocks])
    flags = [
        *(flag for block in blocks for flag in block.quality_flags),
        "layout_wrapped_paragraph",
    ]
    return blocks[0].model_copy(
        update={
            "block_id": block_id,
            "text": text,
            "bbox": bbox,
            "block_type": "paragraph",
            "confidence": min(block.confidence for block in blocks),
            "derived_from_block_ids": [block.block_id for block in blocks],
            "quality_flags": list(dict.fromkeys(flags)),
            "conflict_flags": list(dict.fromkeys(flag for block in blocks for flag in block.conflict_flags)),
        }
    )


def _can_merge_same_line(left: DocumentIRBlock, right: DocumentIRBlock, config: LayoutNormalizationConfig) -> bool:
    if left.page != right.page or len(left.bbox) < 4 or len(right.bbox) < 4:
        return False
    if left.table_id or right.table_id or left.block_type == "cell" or right.block_type == "cell":
        return False
    if abs(float(left.bbox[1]) - float(right.bbox[1])) > config.same_line_y_tolerance:
        return False
    if _starts_independent_field_label(right.text, config):
        return False
    if _horizontal_gap(left.bbox, right.bbox) > _allowed_merge_gap(left.text, config):
        return False
    return True


def _allowed_merge_gap(text: str, config: LayoutNormalizationConfig) -> float:
    if re.search(r"[:：]\s*$", text.strip()):
        return max(config.merge_horizontal_gap, 140.0)
    return config.merge_horizontal_gap


def _starts_independent_field_label(text: str, config: LayoutNormalizationConfig) -> bool:
    return _key_label_start(text, config.key_value_labels) is not None or _generic_field_label_start(text) is not None


def _key_label_start(text: str, labels: list[str]) -> str | None:
    compact = text.strip()
    for label in sorted((label for label in labels if label), key=len, reverse=True):
        if re.match(rf"^{re.escape(label)}\s*[:：]", compact):
            return label
    return None


def _generic_field_label_start(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text.strip())
    match = re.match(r"^([\u4e00-\u9fffA-Za-z0-9（）()·\-]{1,12})[:：]", compact)
    if not match:
        return None
    return match.group(1)


def _horizontal_gap(left_bbox: list[float], right_bbox: list[float]) -> float:
    return float(right_bbox[0]) - float(left_bbox[2])


def _merge_blocks(left: DocumentIRBlock, right: DocumentIRBlock) -> DocumentIRBlock:
    text = f"{left.text.rstrip()} {right.text.lstrip()}".strip()
    block_id = f"{left.block_id}+{right.block_id}"
    bbox = _union_bbox(left.bbox, right.bbox)
    return left.model_copy(
        update={
            "block_id": block_id,
            "text": text,
            "bbox": bbox,
            "confidence": min(left.confidence, right.confidence),
            "quality_flags": list(dict.fromkeys([*left.quality_flags, *right.quality_flags, "layout_merged_line"])),
            "conflict_flags": list(dict.fromkeys([*left.conflict_flags, *right.conflict_flags])),
        }
    )


def _union_bbox(left: list[float], right: list[float]) -> list[float]:
    if len(left) < 4:
        return right
    if len(right) < 4:
        return left
    return [
        min(float(left[0]), float(right[0])),
        min(float(left[1]), float(right[1])),
        max(float(left[2]), float(right[2])),
        max(float(left[3]), float(right[3])),
    ]


def _union_many(boxes: list[list[float]]) -> list[float]:
    valid = [bbox for bbox in boxes if len(bbox) >= 4]
    if not valid:
        return []
    bbox = valid[0]
    for candidate in valid[1:]:
        bbox = _union_bbox(bbox, candidate)
    return bbox


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


def _derive_key_value_blocks(
    blocks: list[DocumentIRBlock],
    config: LayoutNormalizationConfig,
) -> tuple[list[DocumentIRBlock], int, int]:
    labels = [label for label in config.key_value_labels if label]
    if not labels:
        return _renumber_blocks(blocks), 0, 0
    neighbor_blocks = _derive_neighbor_key_value_blocks(blocks, labels, config)
    output: list[DocumentIRBlock] = []
    derived_count = 0
    neighbor_derived_count = sum(len(items) for items in neighbor_blocks.values())
    for block in blocks:
        output.append(block)
        if block.document_region not in config.key_value_source_regions:
            output.extend(neighbor_blocks.get(block.block_id, []))
            continue
        for label, value, start, end in _extract_key_values(block.text, labels, config.key_value_max_value_chars):
            output.append(
                _derive_key_value_block(
                    source=block,
                    label=label,
                    value=value,
                    start=start,
                    end=end,
                    sequence=derived_count + 1,
                )
            )
            derived_count += 1
        output.extend(neighbor_blocks.get(block.block_id, []))
    return _renumber_blocks(output), derived_count + neighbor_derived_count, neighbor_derived_count


def _derive_neighbor_key_value_blocks(
    blocks: list[DocumentIRBlock],
    labels: list[str],
    config: LayoutNormalizationConfig,
) -> dict[str, list[DocumentIRBlock]]:
    by_insert_after: dict[str, list[DocumentIRBlock]] = {}
    sequence = 0
    sequence = _derive_table_cell_key_value_blocks(blocks, labels, config, by_insert_after, sequence)
    sequence = _derive_table_header_key_value_blocks(blocks, labels, config, by_insert_after, sequence)
    sequence = _derive_table_row_header_key_value_blocks(blocks, labels, config, by_insert_after, sequence)
    for line in _same_line_groups(blocks, config.same_line_y_tolerance):
        line_blocks = [block for block in line if len(block.bbox) >= 4]
        for index, block in enumerate(line_blocks):
            if block.document_region not in config.key_value_source_regions:
                continue
            label = _standalone_key_label(block.text, labels)
            if not label:
                continue
            value_blocks: list[DocumentIRBlock] = []
            for candidate in line_blocks[index + 1 :]:
                if _horizontal_gap(block.bbox, candidate.bbox) > config.key_value_neighbor_max_gap:
                    break
                if _standalone_key_label(candidate.text, labels):
                    break
                value = candidate.text.strip(" \t\r\n，,；;。")
                if not value:
                    continue
                value_blocks.append(candidate)
                break
            if not value_blocks:
                continue
            value = " ".join(item.text.strip(" \t\r\n，,；;。") for item in value_blocks).strip()
            if not value or len(value) > config.key_value_max_value_chars:
                continue
            sequence += 1
            derived = _derive_neighbor_key_value_block(label_block=block, value_blocks=value_blocks, label=label, value=value, sequence=sequence)
            by_insert_after.setdefault(value_blocks[-1].block_id, []).append(derived)
    return by_insert_after


def _derive_table_cell_key_value_blocks(
    blocks: list[DocumentIRBlock],
    labels: list[str],
    config: LayoutNormalizationConfig,
    by_insert_after: dict[str, list[DocumentIRBlock]],
    sequence: int,
) -> int:
    rows: dict[tuple[int, str, int], list[DocumentIRBlock]] = {}
    for block in blocks:
        if not block.table_id or block.row is None:
            continue
        rows.setdefault((block.page, block.table_id, block.row), []).append(block)

    for row_blocks in rows.values():
        ordered = sorted(row_blocks, key=lambda item: (item.col if item.col is not None else 9999, item.reading_order, item.block_id))
        for index, block in enumerate(ordered):
            label = _table_cell_key_label(block.text, labels)
            if not label:
                continue
            value_blocks: list[DocumentIRBlock] = []
            for candidate in ordered[index + 1 :]:
                if candidate.col is not None and block.col is not None and candidate.col <= block.col:
                    continue
                if _table_cell_key_label(candidate.text, labels):
                    break
                value = candidate.text.strip(" \t\r\n，,；;。：:")
                if not value:
                    continue
                value_blocks.append(candidate)
                break
            if not value_blocks:
                continue
            value = " ".join(item.text.strip(" \t\r\n，,；;。：:") for item in value_blocks).strip()
            if not value or len(value) > config.key_value_max_value_chars:
                continue
            sequence += 1
            derived = _derive_neighbor_key_value_block(
                label_block=block,
                value_blocks=value_blocks,
                label=label,
                value=value,
                sequence=sequence,
            )
            by_insert_after.setdefault(value_blocks[-1].block_id, []).append(derived)
    return sequence


def _derive_table_header_key_value_blocks(
    blocks: list[DocumentIRBlock],
    labels: list[str],
    config: LayoutNormalizationConfig,
    by_insert_after: dict[str, list[DocumentIRBlock]],
    sequence: int,
) -> int:
    tables: dict[tuple[int, str], list[DocumentIRBlock]] = {}
    for block in blocks:
        if not block.table_id or block.row is None or block.col is None:
            continue
        tables.setdefault((block.page, block.table_id), []).append(block)

    for table_blocks in tables.values():
        rows = sorted({block.row for block in table_blocks if block.row is not None})
        if len(rows) < 2:
            continue
        value_row = rows[-1]
        header_rows = rows[:-1]
        for header in [block for block in table_blocks if block.row in header_rows and _table_cell_span(block)[1] == 1]:
            label = _table_cell_key_label(header.text, labels)
            if not label:
                continue
            value = _nearest_cell_below(header, table_blocks, target_row=value_row)
            if value is None:
                continue
            text_value = value.text.strip(" \t\r\n，,；;。：:")
            if not text_value or len(text_value) > config.key_value_max_value_chars:
                continue
            sequence += 1
            derived = _derive_neighbor_key_value_block(
                label_block=header,
                value_blocks=[value],
                label=label,
                value=text_value,
                sequence=sequence,
                extra_quality_flags=["layout_table_header_key_value_pair"],
            )
            by_insert_after.setdefault(value.block_id, []).append(derived)
    return sequence


def _derive_table_row_header_key_value_blocks(
    blocks: list[DocumentIRBlock],
    labels: list[str],
    config: LayoutNormalizationConfig,
    by_insert_after: dict[str, list[DocumentIRBlock]],
    sequence: int,
) -> int:
    rows: dict[tuple[int, str, int], list[DocumentIRBlock]] = {}
    spanning_labels: dict[tuple[int, str, int], list[DocumentIRBlock]] = {}
    for block in blocks:
        if not block.table_id or block.row is None:
            continue
        rows.setdefault((block.page, block.table_id, block.row), []).append(block)
        for spanned_row in _spanned_rows(block):
            if spanned_row != block.row:
                spanning_labels.setdefault((block.page, block.table_id, spanned_row), []).append(block)

    for row_key, row_blocks in rows.items():
        ordered = sorted(
            [*spanning_labels.get(row_key, []), *row_blocks],
            key=lambda item: (item.col if item.col is not None else 9999, item.reading_order, item.block_id),
        )
        if len(ordered) < 2:
            continue
        label_block = ordered[0]
        label = _table_cell_key_label(label_block.text, labels)
        if not label:
            continue
        value_block = _first_row_value_cell(label_block, ordered, labels)
        if value_block is None:
            continue
        value = value_block.text.strip(" \t\r\n，,；;。：:")
        if not value or len(value) > config.key_value_max_value_chars:
            continue
        if _mark_existing_derived_pair(
            by_insert_after,
            insert_after=value_block.block_id,
            label=label,
            value=value,
            quality_flag="layout_table_row_header_key_value_pair",
        ):
            continue
        sequence += 1
        derived = _derive_neighbor_key_value_block(
            label_block=label_block,
            value_blocks=[value_block],
            label=label,
            value=value,
            sequence=sequence,
            extra_quality_flags=["layout_table_row_header_key_value_pair"],
        )
        by_insert_after.setdefault(value_block.block_id, []).append(derived)
    return sequence


def _mark_existing_derived_pair(
    by_insert_after: dict[str, list[DocumentIRBlock]],
    *,
    insert_after: str,
    label: str,
    value: str,
    quality_flag: str,
) -> bool:
    for index, block in enumerate(by_insert_after.get(insert_after, [])):
        if block.key_label != label or block.value_text != value:
            continue
        by_insert_after[insert_after][index] = block.model_copy(
            update={"quality_flags": list(dict.fromkeys([*block.quality_flags, quality_flag]))}
        )
        return True
    return False


def _nearest_cell_below(
    header: DocumentIRBlock,
    table_blocks: list[DocumentIRBlock],
    *,
    target_row: int | None = None,
) -> DocumentIRBlock | None:
    header_cols = set(_spanned_cols(header))
    candidates = [
        block
        for block in table_blocks
        if block.col in header_cols
        and block.row is not None
        and header.row is not None
        and block.row > header.row
        and (target_row is None or block.row == target_row)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item.row if item.row is not None else 9999, item.reading_order, item.block_id))[0]


def _first_row_value_cell(
    label_block: DocumentIRBlock,
    ordered: list[DocumentIRBlock],
    labels: list[str],
) -> DocumentIRBlock | None:
    label_cols = set(_spanned_cols(label_block))
    candidates: list[DocumentIRBlock] = []
    for candidate in ordered:
        if candidate.block_id == label_block.block_id:
            continue
        if candidate.col is not None and label_block.col is not None and candidate.col <= label_block.col:
            continue
        if candidate.col in label_cols:
            continue
        if _table_cell_key_label(candidate.text, labels):
            continue
        if not candidate.text.strip(" \t\r\n，,；;。：:"):
            continue
        candidates.append(candidate)
    return next((candidate for candidate in candidates if _looks_like_table_value(candidate.text)), None) or (
        candidates[0] if candidates else None
    )


def _looks_like_table_value(text: str) -> bool:
    compact = text.strip(" \t\r\n，,；;。：:")
    return bool(re.fullmatch(r"\d+(?:\.\d+)?|[0-9]+级|[0-9]+分|男|女|是|否", compact, flags=re.IGNORECASE))


def _spanned_cols(block: DocumentIRBlock) -> list[int]:
    if block.col is None:
        return []
    return list(range(block.col, block.col + max(1, block.col_span)))


def _spanned_rows(block: DocumentIRBlock) -> list[int]:
    if block.row is None:
        return []
    return list(range(block.row, block.row + max(1, block.row_span)))


def _table_cell_span(block: DocumentIRBlock) -> tuple[int, int]:
    return max(1, block.row_span), max(1, block.col_span)


def _table_cell_key_label(text: str, labels: list[str]) -> str | None:
    compact = text.strip().strip("：:")
    for label in sorted(labels, key=len, reverse=True):
        if compact == label:
            return label
    return None


def _derive_key_value_block(
    *,
    source: DocumentIRBlock,
    label: str,
    value: str,
    start: int,
    end: int,
    sequence: int,
) -> DocumentIRBlock:
    digest = hashlib.sha1(f"{source.block_id}:{label}:{value}:{start}:{end}".encode("utf-8")).hexdigest()[:8]
    bbox = _estimated_span_bbox(source, start, end)
    flags = [*source.quality_flags, "layout_key_value_pair"]
    if bbox:
        flags.append("layout_estimated_bbox")
    return source.model_copy(
        update={
            "block_id": f"{source.block_id}:kv:{sequence:03d}:{digest}",
            "text": f"{label}：{value}",
            "bbox": bbox,
            "block_type": "key_value",
            "confidence": source.confidence,
            "source_engine": "layout_key_value",
            "stage_source": "layout_key_value_derivation",
            "key_label": label,
            "value_text": value,
            "parent_block_id": source.block_id,
            "derived_from_block_ids": list(dict.fromkeys([*source.derived_from_block_ids, source.block_id])),
            "quality_flags": list(dict.fromkeys(flags)),
        }
    )


def _derive_neighbor_key_value_block(
    *,
    label_block: DocumentIRBlock,
    value_blocks: list[DocumentIRBlock],
    label: str,
    value: str,
    sequence: int,
    extra_quality_flags: list[str] | None = None,
) -> DocumentIRBlock:
    source_ids = [label_block.block_id, *(block.block_id for block in value_blocks)]
    digest = hashlib.sha1(f"{':'.join(source_ids)}:{label}:{value}".encode("utf-8")).hexdigest()[:8]
    bbox = _union_many([label_block.bbox, *(block.bbox for block in value_blocks)])
    confidence_values = [label_block.confidence, *(block.confidence for block in value_blocks)]
    flags = [
        *label_block.quality_flags,
        *(flag for block in value_blocks for flag in block.quality_flags),
        "layout_key_value_pair",
        "layout_neighbor_key_value_pair",
        *(extra_quality_flags or []),
    ]
    return label_block.model_copy(
        update={
            "block_id": f"{label_block.block_id}:neighbor-kv:{sequence:03d}:{digest}",
            "text": f"{label}：{value}",
            "bbox": bbox,
            "block_type": "key_value",
            "confidence": min(confidence_values),
            "source_engine": "layout_key_value",
            "stage_source": "layout_key_value_derivation",
            "key_label": label,
            "value_text": value,
            "parent_block_id": label_block.block_id,
            "derived_from_block_ids": list(dict.fromkeys([*label_block.derived_from_block_ids, *source_ids])),
            "quality_flags": list(dict.fromkeys(flags)),
        }
    )


def _extract_key_values(
    text: str,
    labels: list[str],
    max_value_chars: int,
) -> list[tuple[str, str, int, int]]:
    label_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    if not label_pattern:
        return []
    pattern = re.compile(rf"(?P<label>{label_pattern})\s*[:：]\s*(?P<value>.*?)(?=\s*(?:{label_pattern})\s*[:：]|$)")
    pairs: list[tuple[str, str, int, int]] = []
    for match in pattern.finditer(text):
        label = match.group("label").strip()
        raw_value = match.group("value")
        leading_trim = len(raw_value) - len(raw_value.lstrip(" \t\r\n，,；;"))
        value = raw_value.strip(" \t\r\n，,；;。")
        if not label or not value:
            continue
        if len(value) > max_value_chars:
            continue
        start = match.start("label")
        end = match.start("value") + leading_trim + len(value)
        pairs.append((label, value, start, end))
    return pairs


def _estimated_span_bbox(block: DocumentIRBlock, start: int, end: int) -> list[float]:
    if len(block.bbox) < 4 or not block.text:
        return []
    text_len = max(len(block.text), 1)
    left_ratio = max(0.0, min(1.0, start / text_len))
    right_ratio = max(left_ratio, min(1.0, end / text_len))
    x1, y1, x2, y2 = [float(value) for value in block.bbox[:4]]
    width = x2 - x1
    return [x1 + width * left_ratio, y1, x1 + width * right_ratio, y2]


def _renumber_blocks(blocks: list[DocumentIRBlock]) -> list[DocumentIRBlock]:
    return [block.model_copy(update={"reading_order": index}) for index, block in enumerate(blocks, start=1)]


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


def _is_patient_header(text: str, config: LayoutNormalizationConfig) -> bool:
    count = sum(1 for label in config.patient_header_labels if re.search(rf"{re.escape(label)}\s*[:：]", text))
    return count >= config.patient_header_min_labels


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
