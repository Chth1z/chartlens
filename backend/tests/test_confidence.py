from app.domain.confidence import ReviewBand, score_field_confidence


def test_score_field_confidence_auto_accepts_strong_supported_result():
    result = score_field_confidence(
        model_confidence=0.96,
        ocr_confidence=0.94,
        evidence_strength=0.95,
        rule_consistent=True,
        has_conflict=False,
        has_evidence=True,
    )

    assert result.band == ReviewBand.AUTO_ACCEPT
    assert result.review_required is False
    assert result.score >= 0.90


def test_score_field_confidence_forces_review_for_conflict():
    result = score_field_confidence(
        model_confidence=0.96,
        ocr_confidence=0.95,
        evidence_strength=0.95,
        rule_consistent=True,
        has_conflict=True,
        has_evidence=True,
    )

    assert result.band == ReviewBand.NEEDS_REVIEW
    assert result.review_required is True
    assert "conflict" in result.reasons


def test_score_field_confidence_marks_missing_evidence_unknown():
    result = score_field_confidence(
        model_confidence=0.99,
        ocr_confidence=0.99,
        evidence_strength=0.0,
        rule_consistent=True,
        has_conflict=False,
        has_evidence=False,
    )

    assert result.band == ReviewBand.UNKNOWN
    assert result.review_required is True
    assert result.score < 0.60
