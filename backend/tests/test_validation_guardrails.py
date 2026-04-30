from app.core.config_loader import load_extraction_schema
from app.domain.models import DocumentIR, DocumentIRBlock, ExtractionCandidate
from app.services.validation import validate_candidate


def _document_ir(text: str = "既往史：否认高血压。") -> DocumentIR:
    return DocumentIR(
        document_id="doc-test",
        profile_id="medical_inpatient_zh",
        source_filename="case.txt",
        blocks=[
            DocumentIRBlock(
                block_id="b1",
                page=1,
                reading_order=1,
                text=text,
                confidence=0.98,
                section_label="既往史",
            )
        ],
    )


def test_invalid_enum_is_downgraded_to_unknown():
    schema = load_extraction_schema()
    field = schema.field_by_key("hypertension_history")
    candidate = ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="yes",
        evidence_span="高血压",
        evidence_block_id="b1",
        evidence_type="explicit_positive",
        confidence=0.9,
    )

    result = validate_candidate(candidate, field, _document_ir("既往史：高血压10年。"))

    assert result.normalized_code == "unknown"
    assert result.review_required is True
    assert result.error_code == "INVALID_CODE"


def test_non_unknown_requires_real_evidence_span():
    schema = load_extraction_schema()
    field = schema.field_by_key("hypertension_history")
    candidate = ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="1",
        evidence_span="高血压10年",
        evidence_block_id="b1",
        evidence_type="explicit_positive",
        confidence=0.9,
    )

    result = validate_candidate(candidate, field, _document_ir("既往史：否认高血压。"))

    assert result.normalized_code == "unknown"
    assert result.error_code == "EVIDENCE_SPAN_NOT_FOUND"


def test_no_evidence_cannot_carry_negative_value():
    schema = load_extraction_schema()
    field = schema.field_by_key("hyperlipidemia_history")
    candidate = ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="0",
        evidence_type="no_evidence",
        confidence=0.8,
    )

    result = validate_candidate(candidate, field, _document_ir("既往史：否认高血压。"))

    assert result.normalized_code == "unknown"
    assert result.error_code == "NO_EVIDENCE_VALUE"


def test_derived_candidate_requires_review():
    schema = load_extraction_schema()
    field = schema.field_by_key("wfns_grade")
    candidate = ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="4",
        status="derived_candidate",
        evidence_span="GCS 10",
        evidence_block_id="b1",
        evidence_type="derived",
        confidence=0.7,
        review_required=False,
    )

    result = validate_candidate(candidate, field, _document_ir("体格检查：GCS 10分。"))

    assert result.review_required is True
    assert result.auto_accepted is False
    assert result.error_code == "DERIVED_REQUIRES_REVIEW"
