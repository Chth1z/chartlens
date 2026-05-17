"""OCR block postprocessing — dedup, NMS, line stitching.

Simplifies the original ~650 lines of hand-crafted merge algorithms
with a clearer NMS-first approach while preserving the stitching logic
needed for DirectML tiled OCR output.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from difflib import SequenceMatcher

from app.services.ocr_engine.types import IntelligentOcrBlock
from app.services.ocr_engine.bbox_utils import (
    bbox_rect, bbox_iou, bbox_containment, overlap_length, merge_bboxes,
    clean_text, comparable_ocr_line_signature,
)


OCR_DUPLICATE_IGNORED_CHARS = set(" \t\r\n.,;:!?()[]{}<>\"'`~-/\\|_+*=").union(
    {"\u3001", "\u3002", "\uff0c", "\uff1a", "\uff1b", "\uff01", "\uff1f",
     "\uff08", "\uff09", "\u201c", "\u201d", "\u2018", "\u2019", "\u300a", "\u300b"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def dedupe_ocr_blocks(blocks: list[IntelligentOcrBlock]) -> list[IntelligentOcrBlock]:
    """Deduplicate OCR blocks using IoU + text similarity, then stitch line fragments."""
    deduped: list[IntelligentOcrBlock] = []
    for block in blocks:
        dup_idx = _matching_ocr_block_index(deduped, block)
        if dup_idx is None:
            deduped.append(block)
        elif block.confidence > deduped[dup_idx].confidence:
            deduped[dup_idx] = block
    return _stitch_overlapping_ocr_line_fragments(deduped)


def offset_ocr_blocks(blocks: list[IntelligentOcrBlock], *, offset_x: float, offset_y: float) -> list[IntelligentOcrBlock]:
    if not offset_x and not offset_y:
        return blocks
    shifted: list[IntelligentOcrBlock] = []
    for block in blocks:
        bbox = block.bbox
        shifted_bbox = [bbox[0] + offset_x, bbox[1] + offset_y, bbox[2] + offset_x, bbox[3] + offset_y] if len(bbox) == 4 else bbox
        shifted.append(replace(block, bbox=shifted_bbox))
    return shifted


def ocr_block_selection_score(blocks: list[IntelligentOcrBlock]) -> tuple[int, float]:
    if not blocks:
        return (0, 0.0)
    char_count = sum(len(block.text) for block in blocks)
    avg_confidence = sum(block.confidence for block in blocks) / len(blocks)
    return (char_count, avg_confidence)


# ---------------------------------------------------------------------------
# Dedup internals
# ---------------------------------------------------------------------------

def _matching_ocr_block_index(blocks: list[IntelligentOcrBlock], candidate: IntelligentOcrBlock) -> int | None:
    candidate_text = clean_text(candidate.text)
    if not candidate_text:
        return None
    for index, block in enumerate(blocks):
        if block.page != candidate.page:
            continue
        if not _ocr_duplicate_text_equivalent(clean_text(block.text), candidate_text):
            continue
        # IoU-based match (standard NMS)
        if bbox_iou(block.bbox, candidate.bbox) >= 0.6:
            return index
        # Containment-based match (MinerU-style: one block nested inside another)
        if (bbox_containment(block.bbox, candidate.bbox) >= 0.85
                or bbox_containment(candidate.bbox, block.bbox) >= 0.85):
            return index
    return None


def _ocr_duplicate_text_equivalent(left: str, right: str) -> bool:
    if left == right:
        return True
    left_n = _normalize_ocr_duplicate_text(left)
    right_n = _normalize_ocr_duplicate_text(right)
    if not left_n or not right_n:
        return False
    if left_n == right_n:
        return True
    shorter = min(len(left_n), len(right_n))
    longer = max(len(left_n), len(right_n))
    if shorter < 12:
        return False
    if longer - shorter > max(2, int(longer * 0.08)):
        return False
    return SequenceMatcher(None, left_n, right_n).ratio() >= 0.96


def _normalize_ocr_duplicate_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(c.lower() for c in normalized if c not in OCR_DUPLICATE_IGNORED_CHARS)


# ---------------------------------------------------------------------------
# Line stitching (needed for DirectML tiled OCR)
# ---------------------------------------------------------------------------

def _stitch_overlapping_ocr_line_fragments(blocks: list[IntelligentOcrBlock]) -> list[IntelligentOcrBlock]:
    stitchable = [b for b in blocks if _is_stitchable_text_block(b)]
    passthrough = [b for b in blocks if not _is_stitchable_text_block(b)]
    if len(stitchable) < 2:
        return blocks

    lines: list[list[IntelligentOcrBlock]] = []
    for block in sorted(stitchable, key=_ocr_position_key):
        rect = bbox_rect(block.bbox)
        line = next((c for c in lines if rect and _same_ocr_text_line(c, block.page, rect)), None)
        if line is None:
            lines.append([block])
        else:
            line.append(block)

    ordered: list[tuple[tuple, list[IntelligentOcrBlock]]] = []
    for line in lines:
        ordered.append((_ocr_line_position_key(line), _stitch_ocr_text_line(line)))
    for block in passthrough:
        ordered.append((_ocr_line_position_key([block]), [block]))
    return [b for _, line in sorted(ordered, key=lambda i: i[0]) for b in line]


def _is_stitchable_text_block(block: IntelligentOcrBlock) -> bool:
    if block.block_type not in {"line", "paragraph", "text"}:
        return False
    return bool(clean_text(block.text)) and bbox_rect(block.bbox) is not None


def _same_ocr_text_line(line: list[IntelligentOcrBlock], page: int, rect: tuple) -> bool:
    if not line or line[0].page != page:
        return False
    line_rect = bbox_rect(merge_bboxes([b.bbox for b in line]))
    if line_rect is None:
        return False
    ov = overlap_length(line_rect[1], line_rect[3], rect[1], rect[3])
    min_h = max(1.0, min(line_rect[3] - line_rect[1], rect[3] - rect[1]))
    cd = abs((line_rect[1] + line_rect[3]) / 2 - (rect[1] + rect[3]) / 2)
    return ov / min_h >= 0.55 and cd <= max(line_rect[3] - line_rect[1], rect[3] - rect[1]) * 0.7


def _stitch_ocr_text_line(line: list[IntelligentOcrBlock]) -> list[IntelligentOcrBlock]:
    stitched: list[IntelligentOcrBlock] = []
    for block in sorted(line, key=lambda i: (bbox_rect(i.bbox) or (0, 0, 0, 0))[0]):
        mi = next((idx for idx, item in enumerate(stitched) if _can_stitch_ocr_blocks(item, block)), None)
        if mi is None:
            stitched.append(block)
        else:
            stitched[mi] = _merge_ocr_text_blocks(stitched[mi], block)
    return stitched


def _can_stitch_ocr_blocks(left: IntelligentOcrBlock, right: IntelligentOcrBlock) -> bool:
    lr, rr = bbox_rect(left.bbox), bbox_rect(right.bbox)
    if lr is None or rr is None:
        return False
    ho = overlap_length(lr[0], lr[2], rr[0], rr[2])
    mw = max(1.0, min(lr[2] - lr[0], rr[2] - rr[0]))
    if ho / mw < 0.2:
        return False
    return _merge_ocr_text(left.text, right.text) is not None


def _merge_ocr_text_blocks(left: IntelligentOcrBlock, right: IntelligentOcrBlock) -> IntelligentOcrBlock:
    merged_text = _merge_ocr_text(left.text, right.text) or left.text
    return replace(left, text=merged_text,
        bbox=merge_bboxes([left.bbox, right.bbox]) or left.bbox,
        confidence=max(left.confidence, right.confidence))


def _merge_ocr_text(left: str, right: str) -> str | None:
    lt, rt = clean_text(left), clean_text(right)
    if not lt or not rt: return None
    if lt == rt: return lt
    if lt in rt: return rt
    if rt in lt: return lt
    return (_merge_by_fuzzy_containment(lt, rt)
        or _merge_by_near_duplicate(lt, rt)
        or _merge_by_short_fuzzy_containment(lt, rt)
        or _merge_by_overlap(lt, rt)
        or _merge_by_fuzzy_overlap(lt, rt)
        or _merge_by_common_substring(lt, rt))


def _ocr_position_key(block: IntelligentOcrBlock):
    rect = bbox_rect(block.bbox)
    if rect is None:
        return float(block.page), 0.0, 0.0, clean_text(block.text)
    return float(block.page), rect[1], rect[0], clean_text(block.text)


def _ocr_line_position_key(line: list[IntelligentOcrBlock]):
    if not line:
        return 0.0, 0.0, 0.0, ""
    page = float(line[0].page)
    rect = bbox_rect(merge_bboxes([b.bbox for b in line]))
    if rect is None:
        return page, 0.0, 0.0, clean_text(line[0].text)
    return page, rect[1], rect[0], clean_text(line[0].text)


# ---------------------------------------------------------------------------
# Text merge strategies (preserved from original for regression safety)
# ---------------------------------------------------------------------------

def _bounded_edit_distance(left: str, right: str, max_d: int) -> int:
    if abs(len(left) - len(right)) > max_d:
        return max_d + 1
    prev = list(range(len(right) + 1))
    for li, lc in enumerate(left, 1):
        cur = [li] + [0] * len(right)
        rb = cur[0]
        for ri, rc in enumerate(right, 1):
            sub = 0 if lc == rc else 1
            cur[ri] = min(prev[ri] + 1, cur[ri - 1] + 1, prev[ri - 1] + sub)
            rb = min(rb, cur[ri])
        if rb > max_d:
            return max_d + 1
        prev = cur
    return prev[-1]


def _comp_overlap(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _merge_by_fuzzy_overlap(left: str, right: str) -> str | None:
    for size in range(min(len(left), len(right)), 7, -1):
        ls, rp = _comp_overlap(left[-size:]), _comp_overlap(right[:size])
        if not ls or not rp or ls[0] != rp[0] or ls[-1] != rp[-1]: continue
        me = max(1, int(size * 0.12 + 0.999))
        if _bounded_edit_distance(ls, rp, me) <= me:
            return f"{left}{right[size:]}"
    return None


def _merge_by_fuzzy_containment(left: str, right: str) -> str | None:
    ls, rs = comparable_ocr_line_signature(left), comparable_ocr_line_signature(right)
    mn, mx = min(len(ls), len(rs)), max(len(ls), len(rs))
    if mn < 8 or mx <= mn: return None
    if len(ls) <= len(rs):
        short, long_sig, long_t = ls, rs, right
    else:
        short, long_sig, long_t = rs, ls, left
    me = max(2, int(len(short) * 0.12 + 0.999))
    mw = max(1, len(short) - me)
    xw = min(len(long_sig), len(short) + me)
    for s in range(len(long_sig) - mw + 1):
        for sz in range(mw, xw + 1):
            if s + sz > len(long_sig): break
            if _bounded_edit_distance(short, long_sig[s:s + sz], me) <= me:
                return long_t
    return None


def _merge_by_near_duplicate(left: str, right: str) -> str | None:
    ls, rs = comparable_ocr_line_signature(left), comparable_ocr_line_signature(right)
    mn, mx = min(len(ls), len(rs)), max(len(ls), len(rs))
    if mn < 8 or mx == 0 or mn / mx < 0.82: return None
    if ls == rs:
        return _preferred_variant(left, right)
    if len(ls) == len(rs) and sum(1 for i, c in enumerate(ls) if c == rs[i]) / len(ls) >= 0.92:
        return _preferred_variant(left, right)
    match = _longest_common_fragment(ls, rs, min_size=max(6, int(mn * 0.84)))
    if match and match[2] / mn >= 0.9:
        return _preferred_variant(left, right)
    return None


def _merge_by_short_fuzzy_containment(left: str, right: str) -> str | None:
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    if len(short) < 3 or len(short) > 8 or len(long) < len(short) + 4: return None
    ms = max(2, len(short) - 1)
    match = _longest_common_fragment(long, short, min_size=ms)
    if match is None: return None
    li, si, sz = match
    if len(long) - (li + sz) <= 1 and len(short) - (si + sz) <= 1:
        return long
    return None


def _merge_by_overlap(left: str, right: str) -> str | None:
    for size in range(min(len(left), len(right)), 5, -1):
        if left[-size:] == right[:size]:
            return f"{left}{right[size:]}"
    return None


def _merge_by_common_substring(left: str, right: str) -> str | None:
    match = _longest_common_fragment(left, right, min_size=8)
    if match is None: return None
    li, ri, sz = match
    lt = len(left) - (li + sz)
    rpl = max(2, min(8, len(right) // 6))
    ltl = max(2, min(12, len(left) // 5))
    if ri > rpl or lt > ltl: return None
    common = left[li:li + sz]
    ls, rs = left[li + sz:], right[ri + sz:]
    if not ls: suffix = rs
    elif not rs: suffix = ls
    elif len(rs) >= len(ls) + 2: suffix = rs
    elif len(ls) >= len(rs) + 2: suffix = ls
    else: suffix = ls
    return f"{left[:li]}{common}{suffix}"


def _preferred_variant(left: str, right: str) -> str:
    ls = _variant_score(left)
    rs = _variant_score(right)
    if abs(ls - rs) > 0.1: return left if ls > rs else right
    if len(left) != len(right): return left if len(left) > len(right) else right
    return left


def _variant_score(text: str) -> float:
    score = len(text) / 200
    score += sum(1 for c in text if c in "，、。；：？！") * 2
    score -= text.count(",") * 1.8
    score -= text.count("\ufffd") * 5
    score -= len(re.findall(r"[A-Za-zμΜ][\/／]1", text)) * 4
    return score


def _longest_common_fragment(left: str, right: str, *, min_size: int) -> tuple[int, int, int] | None:
    best = None
    prev = [0] * (len(right) + 1)
    for li, lc in enumerate(left):
        cur = [0] * (len(right) + 1)
        for ri, rc in enumerate(right):
            if lc != rc: continue
            sz = prev[ri] + 1
            cur[ri + 1] = sz
            if sz >= min_size and (best is None or sz > best[2]):
                best = (li - sz + 1, ri - sz + 1, sz)
        prev = cur
    return best


# Backward-compatible aliases
_dedupe_ocr_blocks = dedupe_ocr_blocks
_offset_ocr_blocks = offset_ocr_blocks
_ocr_block_selection_score = ocr_block_selection_score
_matching_ocr_block_index = _matching_ocr_block_index
_stitch_overlapping_ocr_line_fragments = _stitch_overlapping_ocr_line_fragments
_merge_ocr_text = _merge_ocr_text
_merge_ocr_text_by_fuzzy_overlap = _merge_by_fuzzy_overlap
_merge_ocr_text_by_fuzzy_containment = _merge_by_fuzzy_containment
_merge_ocr_text_by_near_duplicate = _merge_by_near_duplicate
_merge_ocr_text_by_short_fuzzy_containment = _merge_by_short_fuzzy_containment
_merge_ocr_text_by_overlap = _merge_by_overlap
_merge_ocr_text_by_common_substring = _merge_by_common_substring
_bounded_edit_distance = _bounded_edit_distance
_ocr_position_key = _ocr_position_key
