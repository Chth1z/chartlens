"""OCR evaluation utilities — CER, WER, and regression testing support.

Aligned with mature OCR evaluation practices:
- Surya uses CER/WER with Unicode normalization
- MinerU benchmarks against ground truth with page-level metrics
- PaddleOCR uses IoU-weighted text accuracy
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.services.ocr_engine.bbox_utils import bbox_iou, comparable_ocr_line_signature


@dataclass
class EvalResult:
    """Result of comparing OCR output against ground truth."""
    document_id: str = ""
    cer: float = 0.0  # Character Error Rate
    wer: float = 0.0  # Word Error Rate
    page_results: list[dict[str, Any]] = field(default_factory=list)
    block_count: int = 0
    char_count: int = 0
    truth_char_count: int = 0
    avg_confidence: float = 0.0
    quality_band: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "cer": round(self.cer, 4),
            "wer": round(self.wer, 4),
            "block_count": self.block_count,
            "char_count": self.char_count,
            "truth_char_count": self.truth_char_count,
            "avg_confidence": round(self.avg_confidence, 4),
            "quality_band": self.quality_band,
            "page_results": self.page_results,
        }


def character_error_rate(hypothesis: str, reference: str) -> float:
    """Compute Character Error Rate (CER) using edit distance.

    CER = edit_distance(hypothesis, reference) / len(reference)
    Lower is better. 0.0 = perfect match.
    """
    hyp = _normalize_for_eval(hypothesis)
    ref = _normalize_for_eval(reference)
    if not ref:
        return 0.0 if not hyp else 1.0
    distance = _edit_distance(hyp, ref)
    return min(1.0, distance / len(ref))


def word_error_rate(hypothesis: str, reference: str) -> float:
    """Compute Word Error Rate (WER) using word-level edit distance.

    WER = edit_distance(hyp_words, ref_words) / len(ref_words)
    """
    hyp_words = _normalize_for_eval(hypothesis).split()
    ref_words = _normalize_for_eval(reference).split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    distance = _edit_distance(hyp_words, ref_words)
    return min(1.0, distance / len(ref_words))


def evaluate_ocr_output(
    ocr_text: str,
    ground_truth: str,
    *,
    document_id: str = "",
    block_count: int = 0,
    avg_confidence: float = 0.0,
) -> EvalResult:
    """Evaluate OCR output against ground truth text."""
    cer = character_error_rate(ocr_text, ground_truth)
    wer = word_error_rate(ocr_text, ground_truth)
    band = _eval_quality_band(cer)
    return EvalResult(
        document_id=document_id,
        cer=cer,
        wer=wer,
        block_count=block_count,
        char_count=len(_normalize_for_eval(ocr_text)),
        truth_char_count=len(_normalize_for_eval(ground_truth)),
        avg_confidence=avg_confidence,
        quality_band=band,
    )


def evaluate_page_level(
    ocr_pages: dict[int, str],
    truth_pages: dict[int, str],
    *,
    document_id: str = "",
) -> EvalResult:
    """Evaluate OCR with page-level ground truth alignment."""
    all_pages = sorted(set(ocr_pages.keys()) | set(truth_pages.keys()))
    page_results = []
    total_cer_sum = 0.0
    total_wer_sum = 0.0
    total_chars = 0

    for page in all_pages:
        ocr_text = ocr_pages.get(page, "")
        truth_text = truth_pages.get(page, "")
        cer = character_error_rate(ocr_text, truth_text)
        wer = word_error_rate(ocr_text, truth_text)
        ref_len = len(_normalize_for_eval(truth_text))
        page_results.append({
            "page": page,
            "cer": round(cer, 4),
            "wer": round(wer, 4),
            "ocr_chars": len(_normalize_for_eval(ocr_text)),
            "truth_chars": ref_len,
            "quality_band": _eval_quality_band(cer),
        })
        total_cer_sum += cer * max(1, ref_len)
        total_wer_sum += wer * max(1, ref_len)
        total_chars += max(1, ref_len)

    avg_cer = total_cer_sum / total_chars if total_chars > 0 else 0.0
    avg_wer = total_wer_sum / total_chars if total_chars > 0 else 0.0

    return EvalResult(
        document_id=document_id,
        cer=avg_cer,
        wer=avg_wer,
        page_results=page_results,
        char_count=sum(p["ocr_chars"] for p in page_results),
        truth_char_count=sum(p["truth_chars"] for p in page_results),
        quality_band=_eval_quality_band(avg_cer),
    )


def evaluate_layout_tables(
    document_ir,
    truth_blocks: list[dict[str, Any]],
    truth_tables: list[dict[str, Any]],
    *,
    bbox_iou_threshold: float = 0.5,
    center_tolerance_px: float = 24.0,
) -> dict[str, Any]:
    blocks = [block.model_dump() if hasattr(block, "model_dump") else dict(block) for block in getattr(document_ir, "blocks", [])]
    block_metrics = _evaluate_truth_blocks(
        blocks,
        truth_blocks,
        bbox_iou_threshold=bbox_iou_threshold,
        center_tolerance_px=center_tolerance_px,
    )
    table_metrics = _evaluate_truth_tables(
        blocks,
        truth_tables,
        bbox_iou_threshold=bbox_iou_threshold,
        center_tolerance_px=center_tolerance_px,
    )
    return {**block_metrics, **table_metrics}


def _normalize_for_eval(text: str) -> str:
    """Normalize text for fair evaluation comparison."""
    import re
    # Unicode NFKC normalization
    normalized = unicodedata.normalize("NFKC", text)
    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _evaluate_truth_blocks(
    prediction_blocks: list[dict[str, Any]],
    truth_blocks: list[dict[str, Any]],
    *,
    bbox_iou_threshold: float,
    center_tolerance_px: float,
) -> dict[str, Any]:
    matches = _match_truth_to_predictions(
        truth_blocks,
        prediction_blocks,
        require_table_key=False,
    )
    truth_count = len(truth_blocks)
    matched_count = len(matches)
    bbox_hits = sum(1 for truth, prediction, _score in matches if bbox_iou(_bbox(truth), _bbox(prediction)) >= bbox_iou_threshold)
    center_hits = sum(1 for truth, prediction, _score in matches if _center_distance(_bbox(truth), _bbox(prediction)) <= center_tolerance_px)
    order_hits = sum(
        1
        for truth, prediction, _score in matches
        if int(truth.get("reading_order", -1) or -1) == int(prediction.get("reading_order", -2) or -2)
    )
    return {
        "truth_block_count": truth_count,
        "matched_block_count": matched_count,
        "block_text_match_accuracy": _ratio(matched_count, truth_count),
        "block_bbox_iou_accuracy": _ratio(bbox_hits, truth_count),
        "block_center_accuracy": _ratio(center_hits, truth_count),
        "reading_order_accuracy": _ratio(order_hits, truth_count),
        "layout_match_details": [
            {
                "page": truth.get("page", 1),
                "truth_text": str(truth.get("text", "")),
                "predicted_text": str(prediction.get("text", "")),
                "truth_reading_order": truth.get("reading_order"),
                "predicted_reading_order": prediction.get("reading_order"),
                "bbox_iou": round(bbox_iou(_bbox(truth), _bbox(prediction)), 4),
                "center_distance": round(_center_distance(_bbox(truth), _bbox(prediction)), 2),
            }
            for truth, prediction, _score in matches[:20]
        ],
    }


def _evaluate_truth_tables(
    prediction_blocks: list[dict[str, Any]],
    truth_tables: list[dict[str, Any]],
    *,
    bbox_iou_threshold: float,
    center_tolerance_px: float,
) -> dict[str, Any]:
    truth_cells = list(_truth_table_cells(truth_tables))
    prediction_cells = [
        block
        for block in prediction_blocks
        if block.get("block_type") == "cell" or block.get("row") is not None or block.get("col") is not None
    ]
    matches = _match_truth_to_predictions(truth_cells, prediction_cells or prediction_blocks, require_table_key=False)
    truth_count = len(truth_cells)
    text_hits = len(matches)
    key_hits = sum(1 for truth, prediction, _score in matches if _same_table_key(truth, prediction))
    bbox_hits = sum(
        1
        for truth, prediction, _score in matches
        if bbox_iou(_bbox(truth), _bbox(prediction)) >= bbox_iou_threshold
        or _center_distance(_bbox(truth), _bbox(prediction)) <= center_tolerance_px
    )
    return {
        "truth_table_cell_count": truth_count,
        "matched_table_cell_count": len(matches),
        "table_cell_text_accuracy": _ratio(text_hits, truth_count),
        "table_cell_key_accuracy": _ratio(key_hits, truth_count),
        "table_cell_bbox_accuracy": _ratio(bbox_hits, truth_count),
        "table_match_details": [
            {
                "table_id": truth.get("table_id"),
                "page": truth.get("page", 1),
                "row": truth.get("row"),
                "col": truth.get("col"),
                "truth_text": str(truth.get("text", "")),
                "predicted_text": str(prediction.get("text", "")),
                "predicted_row": prediction.get("row"),
                "predicted_col": prediction.get("col"),
                "bbox_iou": round(bbox_iou(_bbox(truth), _bbox(prediction)), 4),
            }
            for truth, prediction, _score in matches[:20]
        ],
    }


def _match_truth_to_predictions(
    truth_items: list[dict[str, Any]],
    prediction_items: list[dict[str, Any]],
    *,
    require_table_key: bool,
) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    used: set[int] = set()
    matches: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for truth in truth_items:
        candidates = []
        for index, prediction in enumerate(prediction_items):
            if index in used:
                continue
            if int(prediction.get("page", 1) or 1) != int(truth.get("page", 1) or 1):
                continue
            if require_table_key and not _same_table_key(truth, prediction):
                continue
            score = _text_similarity(truth.get("text", ""), prediction.get("text", ""))
            if score >= 0.82:
                candidates.append((score, bbox_iou(_bbox(truth), _bbox(prediction)), index, prediction))
        if not candidates:
            continue
        score, _iou, index, prediction = max(candidates, key=lambda item: (item[0], item[1]))
        used.add(index)
        matches.append((truth, prediction, score))
    return matches


def _truth_table_cells(truth_tables: list[dict[str, Any]]):
    for table in truth_tables:
        page = int(table.get("page", 1) or 1)
        table_id = table.get("table_id")
        cells = table.get("cells", [])
        if not isinstance(cells, list):
            continue
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            yield {**cell, "page": int(cell.get("page", page) or page), "table_id": cell.get("table_id", table_id)}


def _same_table_key(truth: dict[str, Any], prediction: dict[str, Any]) -> bool:
    return (
        int(truth.get("row", -1) or -1) == int(prediction.get("row", -2) or -2)
        and int(truth.get("col", -1) or -1) == int(prediction.get("col", -2) or -2)
    )


def _text_similarity(left: object, right: object) -> float:
    left_sig = comparable_ocr_line_signature(str(left or ""))
    right_sig = comparable_ocr_line_signature(str(right or ""))
    if not left_sig and not right_sig:
        return 1.0
    if not left_sig or not right_sig:
        return 0.0
    if left_sig == right_sig:
        return 1.0
    return SequenceMatcher(None, left_sig, right_sig).ratio()


def _bbox(item: dict[str, Any]) -> list[float]:
    bbox = item.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return []
    try:
        return [float(value) for value in bbox]
    except Exception:
        return []


def _center_distance(left: list[float], right: list[float]) -> float:
    if len(left) != 4 or len(right) != 4:
        return float("inf")
    lx = (left[0] + left[2]) / 2
    ly = (left[1] + left[3]) / 2
    rx = (right[0] + right[2]) / 2
    ry = (right[1] + right[3]) / 2
    return ((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _edit_distance(seq1, seq2) -> int:
    """Compute Levenshtein edit distance between two sequences."""
    m, n = len(seq1), len(seq2)
    if m == 0:
        return n
    if n == 0:
        return m

    # Use two-row optimization for memory efficiency
    prev = list(range(n + 1))
    curr = [0] * (n + 1)

    for i in range(1, m + 1):
        curr[0] = i
        for j in range(1, n + 1):
            cost = 0 if seq1[i - 1] == seq2[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,      # deletion
                curr[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev, curr = curr, prev

    return prev[n]


def _eval_quality_band(cer: float) -> str:
    """Classify CER into quality bands."""
    if cer <= 0.01:
        return "excellent"
    if cer <= 0.05:
        return "good"
    if cer <= 0.10:
        return "fair"
    if cer <= 0.25:
        return "poor"
    return "very_poor"
