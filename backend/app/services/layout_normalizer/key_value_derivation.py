from __future__ import annotations

import hashlib
import re

from app.domain.models import DocumentIRBlock, LayoutNormalizationConfig

from app.services.layout_normalizer.block_merging import (
    _horizontal_gap,
    _same_line_groups,
    _union_many,
)
from app.services.layout_normalizer.sections import (
    _renumber_blocks,
    _standalone_key_label,
)


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
