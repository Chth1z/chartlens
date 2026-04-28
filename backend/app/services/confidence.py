from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewBand(StrEnum):
    AUTO_ACCEPT = "auto_accept"
    NEEDS_REVIEW = "needs_review"
    UNKNOWN = "unknown"


class ConfidenceDecision(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    band: ReviewBand
    review_required: bool
    reasons: list[str]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_field_confidence(
    *,
    model_confidence: float,
    ocr_confidence: float,
    evidence_strength: float,
    rule_consistent: bool,
    has_conflict: bool,
    has_evidence: bool,
) -> ConfidenceDecision:
    reasons: list[str] = []
    model_confidence = _clamp(model_confidence)
    ocr_confidence = _clamp(ocr_confidence)
    evidence_strength = _clamp(evidence_strength)

    if not has_evidence:
        reasons.append("missing_evidence")
        return ConfidenceDecision(
            score=0.0,
            band=ReviewBand.UNKNOWN,
            review_required=True,
            reasons=reasons,
        )

    score = (
        model_confidence * 0.45
        + ocr_confidence * 0.25
        + evidence_strength * 0.20
        + (0.10 if rule_consistent else 0.0)
    )

    if not rule_consistent:
        reasons.append("rule_inconsistent")
        score -= 0.20
    if has_conflict:
        reasons.append("conflict")
        score -= 0.15

    score = _clamp(score)
    if score < 0.60:
        band = ReviewBand.UNKNOWN
    elif score < 0.90 or has_conflict or not rule_consistent:
        band = ReviewBand.NEEDS_REVIEW
    else:
        band = ReviewBand.AUTO_ACCEPT

    return ConfidenceDecision(
        score=score,
        band=band,
        review_required=band != ReviewBand.AUTO_ACCEPT,
        reasons=reasons,
    )
