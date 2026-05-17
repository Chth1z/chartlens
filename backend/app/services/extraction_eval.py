"""Field extraction evaluation service.

Shared by:
- the FastAPI routes `/api/evals` and `/api/evals/batch` and `/api/evals/profiles/{id}/run`;
- the CLI runner `scripts/run-extraction-eval.py`.

The service evaluates the field results that are already stored on a
processed case against a gold dictionary. It does not run extraction itself;
the case must have been processed (or reprocessed) before the runner is
invoked. This matches the OCR regression contract where each runner has a
single, narrow responsibility.

Report schema is intentionally stable so before/after diffs of precision
runs (per `AGENTS.md` Precision Tasks) are mechanical.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config_loader import load_evaluation_profile
from app.core.database import (
    CaseRecord,
    FieldResultRecord,
    get_case_or_none,
    json_loads,
)
from app.domain.models import ValidatedFieldResult, EvaluationProfile


REPORT_SCHEMA_VERSION = "extraction-eval-v1"


def run_extraction_evaluation_profile(
    profile_id: str,
    *,
    db: Session,
) -> dict[str, Any]:
    """Evaluate an extraction profile by id.

    Returns a stable report dict with keys: ``schema_version``, ``profile``,
    ``summary``, ``cases``. When the profile has no gold cases the report is
    a template blocker (``summary.hard_blocker = "no_gold_cases"``); CLI
    callers should treat that as a non-zero exit unless explicitly allowed.
    """
    profile = load_evaluation_profile(profile_id)
    return run_extraction_evaluation(profile, db=db)


def run_extraction_evaluation(
    profile: EvaluationProfile,
    *,
    db: Session,
) -> dict[str, Any]:
    profile_payload = _profile_payload(profile)
    if not profile.gold_cases:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "profile": profile_payload,
            "summary": _template_summary(profile.thresholds),
            "cases": [],
        }
    case_results = [
        evaluate_case_against_gold(item.case_id, item.gold, db, tags=item.tags)
        for item in profile.gold_cases
    ]
    summary = summarize_eval_cases(case_results, field_tags=profile.field_tags)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "profile": profile_payload,
        "summary": summary,
        "cases": case_results,
    }


def evaluate_case_against_gold(
    case_id: str,
    gold: dict[str, str],
    db: Session,
    *,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Compare a single processed case against its gold dictionary.

    Returns a per-case payload with field-level metrics. If the case has not
    been processed (no row in ``cases``), the report includes
    ``status="missing_case"`` and zero counts so the summary still aggregates
    cleanly.
    """
    case = get_case_or_none(db, case_id)
    if case is None:
        return _missing_case_payload(case_id, gold, tags=tags or [])

    results = {result.field_key: result for result in _results_for_case(db, case_id)}
    field_metrics: list[dict[str, Any]] = []
    correct = 0
    predicted_non_unknown = 0
    gold_non_unknown = 0
    true_positive = 0
    expected_unknown = 0
    unknown_misfills = 0
    evidence_covered = 0
    auto_accept_count = 0
    auto_accept_correct = 0
    for field_key, expected in gold.items():
        result = results.get(field_key)
        actual = result.normalized_code if result else None
        is_correct = actual == expected
        correct += int(is_correct)
        if expected != "unknown":
            gold_non_unknown += 1
        else:
            expected_unknown += 1
        if actual not in (None, "unknown"):
            predicted_non_unknown += 1
            evidence_covered += int(bool(result and result.evidence_span and result.evidence_block_id))
            if expected == "unknown":
                unknown_misfills += 1
        if actual == expected and expected != "unknown":
            true_positive += 1
        if result and result.auto_accepted:
            auto_accept_count += 1
            auto_accept_correct += int(is_correct)
        field_metrics.append(
            {
                "field_key": field_key,
                "expected": expected,
                "actual": actual,
                "correct": is_correct,
                "auto_accepted": bool(result.auto_accepted) if result else False,
                "has_evidence": bool(result and result.evidence_span and result.evidence_block_id),
                "review_required": bool(result.review_required) if result else True,
                "error_code": result.error_code if result else "MISSING_RESULT",
            }
        )

    diagnostics = json_loads(case.diagnostics_json, {})
    usage = _usage_totals(diagnostics)
    total = len(gold)
    return {
        "case_id": case_id,
        "status": "evaluated",
        "total_fields": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "precision": true_positive / predicted_non_unknown if predicted_non_unknown else 0.0,
        "recall": true_positive / gold_non_unknown if gold_non_unknown else 0.0,
        "auto_accept_count": auto_accept_count,
        "auto_accept_correct": auto_accept_correct,
        "auto_accept_precision": auto_accept_correct / auto_accept_count if auto_accept_count else 0.0,
        "unknown_misfills": unknown_misfills,
        "expected_unknown": expected_unknown,
        "unknown_misfill_rate": unknown_misfills / expected_unknown if expected_unknown else 0.0,
        "predicted_non_unknown": predicted_non_unknown,
        "evidence_covered": evidence_covered,
        "evidence_coverage": evidence_covered / predicted_non_unknown if predicted_non_unknown else 1.0,
        "usage": usage,
        "tags": tags or [],
        "ocr_quality": _case_ocr_quality(case),
        "fields": field_metrics,
    }


def summarize_eval_cases(
    case_results: list[dict[str, Any]],
    *,
    field_tags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    evaluated = [item for item in case_results if item.get("status") == "evaluated"]
    blocked = [item for item in case_results if item.get("status") != "evaluated"]
    totals = {
        "total_fields": sum(item["total_fields"] for item in evaluated),
        "correct": sum(item["correct"] for item in evaluated),
        "auto_accept_count": sum(item["auto_accept_count"] for item in evaluated),
        "auto_accept_correct": sum(item["auto_accept_correct"] for item in evaluated),
        "unknown_misfills": sum(item["unknown_misfills"] for item in evaluated),
        "expected_unknown": sum(item["expected_unknown"] for item in evaluated),
        "predicted_non_unknown": sum(item["predicted_non_unknown"] for item in evaluated),
        "evidence_covered": sum(item["evidence_covered"] for item in evaluated),
        "input_tokens": sum(item["usage"]["input_tokens"] for item in evaluated),
        "output_tokens": sum(item["usage"]["output_tokens"] for item in evaluated),
        "cost_usd": sum(item["usage"]["cost_usd"] for item in evaluated),
    }
    auto_accept_count = totals["auto_accept_count"]
    field_tag_summary = _field_tag_summary(evaluated, field_tags or {})
    quality_bands = _ocr_quality_band_counts(evaluated)
    summary: dict[str, Any] = {
        **totals,
        "case_count": len(case_results),
        "evaluated_case_count": len(evaluated),
        "blocked_case_count": len(blocked),
        "accuracy": totals["correct"] / totals["total_fields"] if totals["total_fields"] else 0.0,
        "auto_accept_precision": (
            totals["auto_accept_correct"] / totals["auto_accept_count"] if totals["auto_accept_count"] else 0.0
        ),
        "unknown_misfill_rate": (
            totals["unknown_misfills"] / totals["expected_unknown"] if totals["expected_unknown"] else 0.0
        ),
        "evidence_coverage": (
            totals["evidence_covered"] / totals["predicted_non_unknown"] if totals["predicted_non_unknown"] else 1.0
        ),
        "tokens_per_case": totals["input_tokens"] / len(evaluated) if evaluated else 0.0,
        "tokens_per_accepted_field": totals["input_tokens"] / auto_accept_count if auto_accept_count else 0.0,
        "field_tags": field_tag_summary,
        "ocr_quality_bands": quality_bands,
    }
    if blocked:
        summary["hard_blocker"] = "missing_processed_cases"
        summary["blocked_case_ids"] = [item["case_id"] for item in blocked]
    return summary


def _profile_payload(profile: EvaluationProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "label": profile.label,
        "schema_id": profile.schema_id,
        "thresholds": profile.thresholds,
        "token_budget": profile.token_budget,
        "gold_case_count": len(profile.gold_cases),
    }


def _template_summary(thresholds: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_count": 0,
        "evaluated_case_count": 0,
        "blocked_case_count": 0,
        "total_fields": 0,
        "correct": 0,
        "accuracy": 0.0,
        "auto_accept_precision": 0.0,
        "unknown_misfill_rate": 0.0,
        "evidence_coverage": 1.0,
        "tokens_per_case": 0.0,
        "tokens_per_accepted_field": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "auto_accept_count": 0,
        "auto_accept_correct": 0,
        "unknown_misfills": 0,
        "expected_unknown": 0,
        "predicted_non_unknown": 0,
        "evidence_covered": 0,
        "field_tags": {},
        "ocr_quality_bands": {},
        "thresholds": thresholds,
        "hard_blocker": "no_gold_cases",
        "hard_blocker_message": (
            "Evaluation profile has no gold cases. Add at least one entry to gold_cases "
            "in the profile YAML before running this profile."
        ),
    }


def _missing_case_payload(case_id: str, gold: dict[str, str], *, tags: list[str]) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": "missing_case",
        "total_fields": len(gold),
        "correct": 0,
        "accuracy": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "auto_accept_count": 0,
        "auto_accept_correct": 0,
        "auto_accept_precision": 0.0,
        "unknown_misfills": 0,
        "expected_unknown": sum(1 for value in gold.values() if value == "unknown"),
        "unknown_misfill_rate": 0.0,
        "predicted_non_unknown": 0,
        "evidence_covered": 0,
        "evidence_coverage": 1.0,
        "usage": {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "cost_usd": 0.0},
        "tags": tags,
        "ocr_quality": {
            "quality_band": "unknown",
            "page_quality": [],
            "ocr_engine": None,
            "ocr_cache_status": None,
        },
        "fields": [
            {
                "field_key": field_key,
                "expected": expected,
                "actual": None,
                "correct": False,
                "auto_accepted": False,
                "has_evidence": False,
                "review_required": True,
                "error_code": "CASE_NOT_PROCESSED",
            }
            for field_key, expected in gold.items()
        ],
        "blocker_message": (
            f"Case '{case_id}' is not present in the database. Upload and process the case "
            "before running this evaluation profile."
        ),
    }


def _results_for_case(db: Session, case_id: str) -> list[ValidatedFieldResult]:
    rows = db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).all()
    parsed: list[ValidatedFieldResult] = []
    for row in rows:
        if not row.payload_json:
            continue
        try:
            data = json.loads(row.payload_json)
        except Exception:
            continue
        try:
            parsed.append(ValidatedFieldResult.model_validate(data))
        except Exception:
            continue
    return parsed


def _field_tag_summary(case_results: list[dict[str, Any]], field_tags: dict[str, list[str]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, int]] = {}
    for case in case_results:
        for field in case.get("fields", []):
            tags = field_tags.get(field.get("field_key"), [])
            for tag in tags:
                bucket = buckets.setdefault(
                    tag,
                    {"total": 0, "correct": 0, "auto_accept_count": 0, "auto_accept_correct": 0},
                )
                bucket["total"] += 1
                bucket["correct"] += int(bool(field.get("correct")))
                if field.get("auto_accepted"):
                    bucket["auto_accept_count"] += 1
                    bucket["auto_accept_correct"] += int(bool(field.get("correct")))
    return {
        tag: {
            **bucket,
            "accuracy": bucket["correct"] / bucket["total"] if bucket["total"] else 0.0,
            "auto_accept_precision": (
                bucket["auto_accept_correct"] / bucket["auto_accept_count"] if bucket["auto_accept_count"] else 0.0
            ),
        }
        for tag, bucket in buckets.items()
    }


def _ocr_quality_band_counts(case_results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in case_results:
        band = str(case.get("ocr_quality", {}).get("quality_band") or "unknown")
        counts[band] = counts.get(band, 0) + 1
    return counts


def _case_ocr_quality(case: CaseRecord) -> dict[str, Any]:
    document = json.loads(case.document_ir_json) if case.document_ir_json else {"blocks": [], "metadata": {}}
    diagnostics = json_loads(case.diagnostics_json, {})
    metadata = document.get("metadata", {}) if isinstance(document, dict) else {}
    quality = diagnostics.get("quality", {}) if isinstance(diagnostics, dict) else {}
    return {
        "quality_band": quality.get("quality_band") or metadata.get("quality_band") or "unknown",
        "page_quality": metadata.get("ocr_page_quality", []),
        "ocr_engine": metadata.get("ocr_engine") or quality.get("ocr_engine"),
        "ocr_cache_status": metadata.get("ocr_cache_status") or quality.get("ocr_cache_status"),
    }


def _usage_totals(diagnostics: dict[str, Any]) -> dict[str, Any]:
    totals = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "cost_usd": 0.0}
    for item in diagnostics.get("llm_usage", []):
        usage = item.get("usage", {}) if isinstance(item, dict) else {}
        totals["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
        totals["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
        totals["cached_input_tokens"] += int(usage.get("cached_input_tokens", 0) or 0)
        totals["cost_usd"] += float(usage.get("cost_usd", 0.0) or 0.0)
    return totals
