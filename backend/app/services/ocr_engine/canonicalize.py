"""Hybrid OCR pipeline canonicalization — merge multi-stage results."""
from __future__ import annotations
import hashlib
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Any
from app.domain.models import OcrProfile
from app.services.ocr_engine.types import IntelligentOcrBlock, IntelligentOcrResult
from app.services.ocr_engine.bbox_utils import bbox_rect, bbox_iou, overlap_length, clean_text
from app.services.ocr_engine.engine_base import (
    ocr_stage_config, engine_metadata, current_accelerator, _opt_str, _opt_int,
)

CANONICAL_LAYOUT_VERSION = "ocr-canonical-layout-v3"


def hybrid_model_stages(profile):
    stages = profile.pipeline_stages or ["preprocess", "paddleocr_vl", "pp_structure_v3", "pp_ocr_v5", "merge"]
    return [s for s in stages if s not in {"preprocess", "merge"}]


def hybrid_required_model_stages(profile):
    return [s for s in hybrid_model_stages(profile) if _hybrid_stage_required(profile, s)]


def hybrid_execution_stages(profile):
    stages = hybrid_model_stages(profile)
    preferred = ["paddleocr_vl", "pp_structure_v3", "pp_ocr_v5"]
    return [s for s in preferred if s in stages] + [s for s in stages if s not in preferred]


def _hybrid_stage_required(profile, stage):
    sc = ocr_stage_config(profile, stage)
    return sc.get("required", True) is not False and sc.get("enabled", True) is not False


def merge_hybrid_ocr_results(stage_results, *, profile, stage_errors=None, stage_unavailable=None):
    raw_blocks, candidate_sets, stage_metrics = [], {}, {}
    for stage in hybrid_model_stages(profile):
        result = stage_results.get(stage)
        if result is None:
            candidate_sets[stage] = []
            stage_metrics[stage] = {
                "engine": ocr_stage_config(profile, stage).get("engine_id", stage),
                "block_count": 0, "char_count": 0, "avg_confidence": 0.0,
                "status": "unavailable" if stage in (stage_unavailable or {}) else "failed",
            }
            continue
        stage_metrics[stage] = {
            "engine": result.engine, "block_count": len(result.blocks),
            "char_count": result.char_count, "avg_confidence": round(result.avg_confidence, 4),
            "model_name": result.metadata.get("model_name"),
            "model_version": result.metadata.get("model_version"),
            "accelerator": result.metadata.get("accelerator"), "status": "completed",
        }
        candidate_sets[stage] = []
        for idx, block in enumerate(result.blocks, start=1):
            gid = _hybrid_candidate_group_id(block)
            cid = _hybrid_candidate_id(stage, idx, block)
            cflags = list(block.conflict_flags)
            if stage in (stage_errors or {}): cflags.append("stage_error")
            enriched = replace(block, stage_source=stage, candidate_id=cid,
                candidate_group_id=gid, conflict_flags=list(dict.fromkeys(cflags)),
                model_name=block.model_name or _opt_str(result.metadata, "model_name"),
                model_version=block.model_version or _opt_str(result.metadata, "model_version"),
                model_variant=block.model_variant or _opt_str(result.metadata, "model_variant"),
                render_dpi=block.render_dpi or _opt_int(result.metadata, "render_dpi") or profile.render_dpi,
                preprocess_profile=block.preprocess_profile or _opt_str(result.metadata, "preprocess_profile") or profile.preprocess_profile,
                coordinate_system=block.coordinate_system or "source_page_pixels")
            raw_blocks.append(enriched)
            candidate_sets[stage].append(_hybrid_candidate_payload(enriched))

    canonical, suppressed = canonicalize_hybrid_ocr_blocks(raw_blocks)
    canonical = recover_grid_table_cells(canonical)
    layout_regions = [_hybrid_layout_region_payload(b) for b in canonical if b.block_type not in {"cell", "table"}]
    coord = {"coordinate_system": "source_page_pixels", "render_dpi": profile.render_dpi,
             "preprocess_profile": profile.preprocess_profile,
             "merge_policy_version": profile.merge_policy_version or CANONICAL_LAYOUT_VERSION}
    metadata = {
        "pipeline_stages": profile.pipeline_stages or ["preprocess", "paddleocr_vl", "pp_structure_v3", "pp_ocr_v5", "merge"],
        "canonical_blocks_version": profile.merge_policy_version or CANONICAL_LAYOUT_VERSION,
        "stage_metrics": stage_metrics, "stage_errors": stage_errors or {},
        "stage_unavailable": stage_unavailable or {}, "candidate_sets": candidate_sets,
        "raw_candidates": candidate_sets,
        "suppressed_candidates": [_hybrid_candidate_payload(b) for b in suppressed],
        "layout_regions": layout_regions,
        "pages": _hybrid_page_summary(canonical), "tables": _hybrid_table_summary(canonical),
        "cells": [_hybrid_candidate_payload(b) for b in canonical if b.block_type == "cell"],
        "order_metrics": {"canonical_block_count": len(canonical), "raw_candidate_count": len(raw_blocks),
                          "suppressed_candidate_count": len(suppressed),
                          "duplicate_box_rate": round(len(suppressed) / len(raw_blocks), 4) if raw_blocks else 0.0},
        "coordinate_transform": coord, "debug_artifacts": {},
        "raw_markdown": _first_metadata_value(stage_results, "raw_markdown") or _first_metadata_value(stage_results, "ocr_docling_export"),
        "render_dpi": profile.render_dpi, "preprocess_profile": profile.preprocess_profile,
        "merge_policy_version": profile.merge_policy_version or CANONICAL_LAYOUT_VERSION,
        **engine_metadata("PaddleOCR hybrid", profile.version, accelerator=current_accelerator()),
    }
    return IntelligentOcrResult(engine="paddleocr_hybrid", blocks=canonical, metadata=metadata)


def canonicalize_hybrid_ocr_blocks(raw_blocks):
    grouped, suppressed_noise = [], []
    for block in sorted(raw_blocks, key=_hybrid_raw_candidate_sort_key):
        if not _hybrid_candidate_is_meaningful(block):
            suppressed_noise.append(replace(block, merge_flags=list(dict.fromkeys([*block.merge_flags, "suppressed_noise"]))))
            continue
        matched = next((g for g in grouped if _hybrid_candidates_belong_together(g, block)), None)
        if matched is None: grouped.append([block])
        else: matched.append(block)

    canonical, suppressed = [], list(suppressed_noise)
    for idx, group in enumerate(grouped, start=1):
        selected = min(group, key=_hybrid_canonical_candidate_key)
        source_ids = [b.candidate_id for b in group if b.candidate_id]
        alt_stages = [b.stage_source for b in group if b.stage_source and b.stage_source != selected.stage_source]
        norm_texts = {clean_text(b.text) for b in group if clean_text(b.text)}
        cflags = list(selected.conflict_flags) + alt_stages
        if len(norm_texts) > 1: cflags.append("text_conflict")
        if len(group) > 1: cflags.append("raw_candidate_suppressed")
        cgid = f"canonical:p{max(1, selected.page)}:{idx:04d}"
        c = replace(selected, candidate_group_id=cgid,
            canonical_source_ids=list(dict.fromkeys(source_ids)),
            layout_region_id=selected.layout_region_id or f"layout:p{max(1, selected.page)}:{idx:04d}",
            line_group_id=selected.line_group_id or f"line:p{max(1, selected.page)}:{idx:04d}",
            coordinate_system=selected.coordinate_system or "source_page_pixels",
            merge_confidence=round(selected.confidence, 4),
            conflict_flags=list(dict.fromkeys(cflags)),
            merge_flags=list(dict.fromkeys([*selected.merge_flags, "canonical_selected"])))
        canonical.append(c)
        sid = selected.candidate_id
        suppressed.extend(replace(b, merge_flags=list(dict.fromkeys([*b.merge_flags, "suppressed_duplicate_candidate"])))
            for b in group if b.candidate_id != sid)
    return sorted(canonical, key=_hybrid_canonical_position_key), suppressed


def recover_grid_table_cells(blocks):
    if any(b.block_type == "cell" and b.table_id and b.row is not None and b.col is not None for b in blocks):
        return blocks
    recovered = list(blocks)
    for page in sorted({max(1, b.page) for b in blocks}):
        page_blocks = [(idx, b) for idx, b in enumerate(recovered) if max(1, b.page) == page]
        table_groups = _infer_grid_table_groups(page_blocks)
        for table_index, group in enumerate(table_groups, start=1):
            table_id = f"inferred-grid-p{page}-{table_index}"
            for item in group:
                recovered[item["index"]] = replace(
                    item["block"],
                    bbox=item["bbox"],
                    block_type="cell",
                    table_id=table_id,
                    row=item["row"],
                    col=item["col"],
                    row_span=1,
                    col_span=1,
                    merge_flags=list(dict.fromkeys([*item["block"].merge_flags, "inferred_grid_table_cell"])),
                )
    return sorted(recovered, key=_hybrid_canonical_position_key)


def _infer_grid_table_groups(blocks):
    indexed = [
        (idx, block, bbox_rect(block.bbox))
        for idx, block in blocks
        if block.block_type not in {"cell", "table"} and bbox_rect(block.bbox) is not None and clean_text(block.text)
    ]
    rows = _cluster_axis(indexed, axis="y", tolerance=24.0)
    row_candidates = [row for row in rows if len(row) >= 2]
    groups = []
    for start in range(len(row_candidates)):
        active = [row_candidates[start]]
        for row in row_candidates[start + 1 :]:
            if _row_gap(active[-1], row) > 72.0:
                break
            if len(_shared_column_centers([*active, row])) < 2:
                break
            active.append(row)
            group = _grid_group_from_rows(active)
            if group:
                groups.append(group)
    return _dedupe_inferred_table_groups(groups)


def _cluster_axis(indexed, *, axis, tolerance):
    center_idx = 2 if axis == "x" else 3
    ordered = sorted(indexed, key=lambda item: ((item[2][0] + item[2][2]) / 2.0, item[1].candidate_id or "") if axis == "x" else ((item[2][1] + item[2][3]) / 2.0, item[2][0]))
    clusters = []
    for item in ordered:
        rect = item[2]
        x_center = (rect[0] + rect[2]) / 2.0
        y_center = (rect[1] + rect[3]) / 2.0
        center = x_center if axis == "x" else y_center
        matched = None
        for cluster in clusters:
            cluster_center = sum(member[center_idx] for member in cluster) / len(cluster)
            if abs(center - cluster_center) <= tolerance:
                matched = cluster
                break
        payload = (item[0], item[1], x_center, y_center, rect)
        if matched is None:
            clusters.append([payload])
        else:
            matched.append(payload)
    return [sorted(cluster, key=lambda item: item[4][0]) for cluster in clusters]


def _row_gap(left_row, right_row):
    left_bottom = max(item[4][3] for item in left_row)
    right_top = min(item[4][1] for item in right_row)
    return right_top - left_bottom


def _shared_column_centers(rows):
    centers = []
    for row in rows:
        for _idx, _block, center, _y_center, _rect in row:
            matched = next((bucket for bucket in centers if abs(sum(bucket) / len(bucket) - center) <= 40.0), None)
            if matched is None:
                centers.append([center])
            else:
                matched.append(center)
    return sorted(sum(bucket) / len(bucket) for bucket in centers if len(bucket) >= max(2, len(rows) - 1))


def _grid_group_from_rows(rows):
    if len(rows) < 3:
        return []
    col_centers = _shared_column_centers(rows)
    if len(col_centers) < 2:
        return []
    assigned_rows = []
    for row_index, row in enumerate(rows, start=1):
        assigned = []
        used_cols = set()
        for idx, block, center, _y_center, rect in row:
            nearest_col = min(range(1, len(col_centers) + 1), key=lambda col: abs(center - col_centers[col - 1]))
            if abs(center - col_centers[nearest_col - 1]) > 48.0 or nearest_col in used_cols:
                continue
            used_cols.add(nearest_col)
            assigned.append((idx, block, row_index, nearest_col, rect))
        if len(assigned) < 2:
            return []
        assigned_rows.append(assigned)
    if sum(len(row) for row in assigned_rows) < 6:
        return []
    median_height = _median([item[4][3] - item[4][1] for row in rows for item in row])
    padding = min(12.0, max(4.0, round(median_height * 0.65)))
    row_bounds = _anchor_boundaries([_row_top(row) for row in rows], padding)
    col_bounds = _anchor_boundaries(
        [
            min(item[4][0] for row in rows for item in row if abs(item[2] - center) <= 48.0)
            for center in col_centers
        ],
        padding,
    )
    group = []
    for row in assigned_rows:
        for idx, block, row_number, col_number, _rect in row:
            group.append({
                "index": idx,
                "block": block,
                "row": row_number,
                "col": col_number,
                "bbox": [
                    float(col_bounds[col_number - 1][0]),
                    float(row_bounds[row_number - 1][0]),
                    float(col_bounds[col_number - 1][1]),
                    float(row_bounds[row_number - 1][1]),
                ],
            })
    return group


def _anchor_boundaries(anchors, padding):
    bounds = []
    starts = [float(anchor) - float(padding) for anchor in sorted(anchors)]
    gaps = [starts[index + 1] - starts[index] for index in range(len(starts) - 1)]
    last_gap = _median(gaps) if gaps else float(padding) * 2.0
    for index, start in enumerate(starts):
        right = starts[index + 1] if index < len(starts) - 1 else start + last_gap
        bounds.append((round(start, 2), round(right, 2)))
    return bounds


def _median(values):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _row_center(row):
    return sum(item[3] for item in row) / len(row)


def _row_top(row):
    return min(item[4][1] for item in row)


def _row_bottom(row):
    return max(item[4][3] for item in row)


def _dedupe_inferred_table_groups(groups):
    selected = []
    used = set()
    for group in sorted(groups, key=lambda item: (-len(item), min(cell["index"] for cell in item) if item else 0)):
        indexes = {cell["index"] for cell in group}
        if not indexes or indexes & used:
            continue
        selected.append(group)
        used.update(indexes)
    return selected


def _hybrid_raw_candidate_sort_key(b):
    rect = bbox_rect(b.bbox)
    page = float(b.page)
    y = rect[1] if rect else 0.0
    x = rect[0] if rect else 0.0
    return _hybrid_stage_priority(b.stage_source), page, y, x, clean_text(b.text)

def _hybrid_canonical_candidate_key(b):
    return (_hybrid_stage_priority(b.stage_source), -float(b.confidence), b.candidate_id or "")

def _hybrid_canonical_position_key(b):
    rect = bbox_rect(b.bbox)
    top = rect[1] if rect else 0.0
    left = rect[0] if rect else 0.0
    row_band = _hybrid_row_band(rect)
    if b.block_type == "cell" and b.table_id and b.row is not None and b.col is not None:
        return (max(1, b.page), row_band, 0, str(b.table_id), int(b.row), int(b.col), left, top, clean_text(b.text))
    return (max(1, b.page), row_band, 1, left, top, "", 0, 0, clean_text(b.text))

def _hybrid_stage_priority(stage):
    return {"paddleocr_vl": 0, "pp_structure_v3": 1, "pp_ocr_v5": 2}.get(stage or "", 9)

def _hybrid_row_band(rect):
    if rect is None:
        return 0
    center_y = (rect[1] + rect[3]) / 2.0
    return round(center_y / 48.0)

def _hybrid_candidate_is_meaningful(b):
    text = clean_text(b.text)
    if not text: return False
    if b.block_type not in {"cell", "table"} and text.isdigit() and len(text) <= 3: return False
    rect = bbox_rect(b.bbox)
    if rect is None: return True
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    if b.block_type not in {"cell", "table"} and w * h > 120_000 and len(text) <= 4: return False
    return True

def _hybrid_candidates_belong_together(group, candidate):
    for b in group:
        if b.page != candidate.page: continue
        if _same_hybrid_table_cell(b, candidate): return True
        if _same_hybrid_visual_box(b, candidate): return True
    return False

def _same_hybrid_table_cell(l, r):
    if l.table_id and r.table_id and l.table_id == r.table_id and l.row == r.row and l.col == r.col: return True
    if "cell" in {l.block_type, r.block_type} and bbox_iou(l.bbox, r.bbox) >= 0.25: return True
    return False

def _same_hybrid_visual_box(l, r):
    if bbox_iou(l.bbox, r.bbox) >= 0.5: return True
    lr, rr = bbox_rect(l.bbox), bbox_rect(r.bbox)
    if lr is None or rr is None: return False
    lw, rw = lr[2] - lr[0], rr[2] - rr[0]
    lh, rh = lr[3] - lr[1], rr[3] - rr[1]
    vert = overlap_length(lr[1], lr[3], rr[1], rr[3]) / max(1.0, min(lh, rh))
    horiz = overlap_length(lr[0], lr[2], rr[0], rr[2]) / max(1.0, min(lw, rw))
    if vert < 0.6 or horiz < 0.25: return False
    return _hybrid_text_similarity(l.text, r.text) >= 0.55

def _hybrid_text_similarity(l, r):
    lc, rc = clean_text(l), clean_text(r)
    if not lc or not rc: return 0.0
    if lc == rc: return 1.0
    return SequenceMatcher(None, lc, rc).ratio()


def _hybrid_candidate_id(stage, idx, b):
    d = hashlib.sha1(f"{stage}:{b.page}:{b.text}:{b.bbox}:{b.table_id}:{b.row}:{b.col}".encode("utf-8")).hexdigest()
    return f"{stage}:{idx:04d}:{d[:8]}"

def _hybrid_candidate_group_id(b):
    if b.table_id and b.row is not None and b.col is not None:
        return f"p{max(1, b.page)}:t{b.table_id}:r{b.row}:c{b.col}"
    if b.bbox:
        rb = ",".join(str(round(float(v), 1)) for v in b.bbox[:4])
        return f"p{max(1, b.page)}:{b.block_type}:{rb}"
    d = hashlib.sha1(f"{b.page}:{b.block_type}:{clean_text(b.text)[:80]}".encode("utf-8")).hexdigest()
    return f"p{max(1, b.page)}:{b.block_type}:{d[:10]}"

def _hybrid_candidate_payload(b):
    return {"candidate_id": b.candidate_id, "candidate_group_id": b.candidate_group_id,
        "canonical_source_ids": b.canonical_source_ids, "stage_source": b.stage_source,
        "page": b.page, "text": b.text, "bbox": b.bbox, "confidence": b.confidence,
        "block_type": b.block_type, "table_id": b.table_id, "row": b.row, "col": b.col,
        "row_span": b.row_span, "col_span": b.col_span,
        "model_name": b.model_name, "model_version": b.model_version, "model_variant": b.model_variant,
        "render_dpi": b.render_dpi, "preprocess_profile": b.preprocess_profile,
        "layout_region_id": b.layout_region_id, "line_group_id": b.line_group_id,
        "coordinate_system": b.coordinate_system, "merge_confidence": b.merge_confidence,
        "merge_flags": b.merge_flags, "conflict_flags": b.conflict_flags}

def _hybrid_layout_region_payload(b):
    return {"layout_region_id": b.layout_region_id, "candidate_group_id": b.candidate_group_id,
        "canonical_source_ids": b.canonical_source_ids, "page": b.page, "text": b.text,
        "bbox": b.bbox, "block_type": b.block_type, "stage_source": b.stage_source,
        "confidence": b.confidence, "merge_confidence": b.merge_confidence, "conflict_flags": b.conflict_flags}

def _hybrid_page_summary(blocks):
    pages = sorted({max(1, b.page) for b in blocks})
    return [{"page": p, "block_count": len(pb := [b for b in blocks if max(1, b.page) == p]),
             "avg_confidence": round(sum(b.confidence for b in pb) / len(pb), 4) if pb else 0.0,
             "stage_sources": sorted({b.stage_source for b in pb if b.stage_source})} for p in pages]

def _hybrid_table_summary(blocks):
    tids = sorted({b.table_id for b in blocks if b.table_id})
    return [{"table_id": tid, "page": min((b.page for b in tb), default=1),
             "cell_count": len([b for b in tb if b.block_type == "cell"]),
             "stage_sources": sorted({b.stage_source for b in tb if b.stage_source})}
            for tid in tids for tb in [[b for b in blocks if b.table_id == tid]]]

def _first_metadata_value(sr, key):
    for r in sr.values():
        v = r.metadata.get(key)
        if v: return v
    return None


# Backward-compatible aliases
_canonicalize_hybrid_ocr_blocks = canonicalize_hybrid_ocr_blocks
_merge_hybrid_ocr_results = merge_hybrid_ocr_results
_hybrid_required_model_stages = hybrid_required_model_stages
_hybrid_model_stages = hybrid_model_stages
_hybrid_execution_stages = hybrid_execution_stages
