"""LLM-as-judge evidence faithfulness evaluator (M2-002).

Extends the E0-008 extraction eval runner with an optional judge pass that
scores (DocumentIR block text, evidence_text, normalized_code) faithfulness
on a 1-5 scale. The judge detects cases where evidence_text exists in the
source block but does NOT semantically support the normalized_code — a class
of failure that exact-match eval cannot catch.

Usage (CLI):
    python scripts/run-extraction-eval.py --profile-id mock_general --judge-model deepseek/deepseek-v4-flash

The judge is opt-in and never runs in the default eval path. It requires
an LLM API key and consumes tokens. Results are appended to the eval report
as a `judge` section with per-field faithfulness scores.

Design:
- The judge prompt is minimal and domain-agnostic: it asks whether the
  evidence_text logically supports assigning normalized_code to the field.
- Scoring: 5=perfect support, 4=strong support, 3=partial, 2=weak, 1=no support.
- A field with score <= 2 is flagged as a potential false positive.
- The judge never sees the gold label — it only evaluates evidence quality.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.database import CaseRecord, json_loads
from app.domain.models import ValidatedFieldResult

logger = logging.getLogger(__name__)

JUDGE_PROMPT_VERSION = "eyex-judge-v1"

JUDGE_SYSTEM_PROMPT = """You are an evidence faithfulness judge for a medical document extraction system.

Your task: given a field key, its assigned value (normalized_code), and the evidence text that was cited as support, score how well the evidence actually supports the assigned value.

Scoring scale:
5 = The evidence directly and unambiguously states or implies the assigned value. A human reader would reach the same conclusion.
4 = The evidence strongly supports the value with minor inference needed (e.g., "否认高血压" clearly supports hypertension_history=0).
3 = The evidence partially supports the value but requires domain knowledge or context not present in the text.
2 = The evidence is tangentially related but does not logically support the specific value assigned.
1 = The evidence does not support the value at all, or contradicts it.

Rules:
- Judge ONLY whether the evidence_text supports the normalized_code. Do not consider whether the extraction is "correct" in an absolute sense.
- If evidence_text is empty or null, score 1.
- If normalized_code is "unknown", score 5 (unknown is always valid when evidence is absent).
- Output ONLY a JSON object: {"score": <int 1-5>, "reason": "<one sentence>"}
"""


def build_judge_request(
    field_key: str,
    normalized_code: str | None,
    evidence_text: str | None,
    block_text: str | None,
) -> dict[str, Any]:
    """Build the judge LLM request payload for one field."""
    return {
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "field_key": field_key,
                        "normalized_code": normalized_code or "unknown",
                        "evidence_text": evidence_text or "",
                        "source_block_text": block_text or "",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 128,
    }


def parse_judge_response(text: str) -> dict[str, Any]:
    """Parse the judge model's JSON response into a score + reason."""
    try:
        from json_repair import repair_json

        data = repair_json(text, return_objects=True)
        if isinstance(data, dict):
            return {
                "score": int(data.get("score", 1)),
                "reason": str(data.get("reason", "")),
            }
    except Exception:
        pass
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {
                "score": int(data.get("score", 1)),
                "reason": str(data.get("reason", "")),
            }
    except Exception:
        pass
    return {"score": 0, "reason": "judge_response_parse_failed"}


def judge_field_result(
    result: ValidatedFieldResult,
    document_ir_blocks: dict[str, str],
) -> dict[str, Any]:
    """Prepare judge input for a single field result.

    Returns a dict with the judge request payload and metadata needed
    to correlate the score back to the eval report. Does NOT call the
    LLM — the caller is responsible for batching and sending requests.
    """
    normalized = result.normalized_code or "unknown"
    evidence_text = result.evidence_text or result.evidence_span or ""
    block_text = ""
    if result.evidence_block_id and result.evidence_block_id in document_ir_blocks:
        block_text = document_ir_blocks[result.evidence_block_id]

    # Skip judging unknown results (they're always valid)
    if normalized == "unknown":
        return {
            "field_key": result.field_key,
            "normalized_code": normalized,
            "evidence_text": evidence_text,
            "skip_reason": "unknown_value",
            "score": 5,
            "reason": "unknown values do not require evidence support",
            "request": None,
        }

    # Skip results without evidence (they'll score 1 trivially)
    if not evidence_text:
        return {
            "field_key": result.field_key,
            "normalized_code": normalized,
            "evidence_text": "",
            "skip_reason": "no_evidence_text",
            "score": 1,
            "reason": "no evidence text provided for non-unknown value",
            "request": None,
        }

    request = build_judge_request(
        field_key=result.field_key,
        normalized_code=normalized,
        evidence_text=evidence_text,
        block_text=block_text,
    )
    return {
        "field_key": result.field_key,
        "normalized_code": normalized,
        "evidence_text": evidence_text,
        "skip_reason": None,
        "score": None,  # To be filled after LLM call
        "reason": None,
        "request": request,
    }


def summarize_judge_results(judge_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate judge scores into a summary."""
    scored = [r for r in judge_results if r.get("score") is not None]
    if not scored:
        return {
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "total_judged": 0,
            "mean_score": 0.0,
            "low_faithfulness_count": 0,
            "low_faithfulness_fields": [],
        }

    scores = [r["score"] for r in scored]
    low_faithfulness = [r for r in scored if r["score"] <= 2 and r.get("skip_reason") is None]

    return {
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "total_judged": len(scored),
        "mean_score": round(sum(scores) / len(scores), 3),
        "score_distribution": {
            str(i): len([s for s in scores if s == i]) for i in range(1, 6)
        },
        "low_faithfulness_count": len(low_faithfulness),
        "low_faithfulness_fields": [
            {
                "field_key": r["field_key"],
                "normalized_code": r["normalized_code"],
                "evidence_text": r["evidence_text"][:100],
                "score": r["score"],
                "reason": r.get("reason", ""),
            }
            for r in low_faithfulness
        ],
    }


def prepare_case_judge_inputs(
    case_id: str,
    results: list[ValidatedFieldResult],
    document_ir_json: str | None,
) -> list[dict[str, Any]]:
    """Prepare judge inputs for all non-unknown results in a case.

    Returns a list of judge input dicts (one per field). Items with
    `request=None` are pre-scored (skipped) and don't need an LLM call.
    """
    # Build block_id -> text map from DocumentIR
    blocks_map: dict[str, str] = {}
    if document_ir_json:
        try:
            doc = json.loads(document_ir_json)
            for block in doc.get("blocks", []):
                if isinstance(block, dict) and "block_id" in block:
                    blocks_map[block["block_id"]] = block.get("text", "")
        except Exception:
            pass

    return [judge_field_result(result, blocks_map) for result in results]
