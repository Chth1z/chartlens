from app.schemas.pipeline import EvidenceCandidate
from app.services.field_dictionary import load_field_dictionary
from app.schemas.pipeline import DocumentFragment
from app.services.implicit_negative import apply_implicit_negative
from app.services.rule_extractor import compact_evidence_for_llm, extract_field_by_rules, should_escalate_to_llm


def candidate(field_key: str, text: str, confidence: float = 0.96) -> EvidenceCandidate:
    return EvidenceCandidate(
        field_key=field_key,
        text=text,
        page=1,
        bbox=[0.0, 0.0, 500.0, 24.0],
        ocr_confidence=confidence,
        score=0.92,
    )


def test_rules_extract_gender_and_age_from_configured_patterns():
    dictionary = load_field_dictionary()

    gender = extract_field_by_rules(dictionary.by_key("gender"), [candidate("gender", "基本信息：性别：女 年龄：67岁")])
    age = extract_field_by_rules(dictionary.by_key("age"), [candidate("age", "基本信息：性别：女 年龄：67岁")])

    assert gender.raw_value == "女"
    assert gender.normalized_code == "2"
    assert gender.review_required is False
    assert age.raw_value == "67"
    assert age.normalized_code == "67"


def test_history_rule_handles_negation_without_guessing():
    field = load_field_dictionary().by_key("hypertension_history")

    result = extract_field_by_rules(field, [candidate(field.key, "既往史：否认高血压病史，否认糖尿病病史。")])

    assert result.raw_value == "无"
    assert result.normalized_code == "0"
    assert result.evidence_text == "既往史：否认高血压病史，否认糖尿病病史。"
    assert result.review_required is True
    assert result.error_code == "NEGATED_EVIDENCE_REVIEW"


def test_rule_miss_is_eligible_for_llm_only_when_field_policy_allows_it():
    dictionary = load_field_dictionary()

    age_result = extract_field_by_rules(dictionary.by_key("age"), [])
    gender_result = extract_field_by_rules(dictionary.by_key("gender"), [])

    assert should_escalate_to_llm(dictionary.by_key("age"), age_result) is True
    assert should_escalate_to_llm(dictionary.by_key("gender"), gender_result) is False


def test_compact_evidence_for_llm_respects_character_budget():
    field = load_field_dictionary().by_key("age")
    evidence = [
        candidate("age", "年龄：" + "很长" * 80),
        candidate("age", "年龄：短证据"),
    ]

    compacted = compact_evidence_for_llm(field, evidence, max_chars=24)

    assert len(compacted) == 1
    assert len(compacted[0].text) <= 24
    assert compacted[0].text.endswith("...")


def test_implicit_negative_sets_history_field_to_no_when_section_is_present_without_mentions():
    field = load_field_dictionary().by_key("diabetes_history")
    result = extract_field_by_rules(field, [])
    fragments = [
        DocumentFragment(
            page=1,
            reading_order=1,
            text="既往史：一般健康状况可，否认肝炎、结核等传染病史。",
            section_name="既往史",
            block_type="paragraph",
            confidence=0.93,
        )
    ]

    updated = apply_implicit_negative(field, result, fragments, quality_band="good")

    assert updated.normalized_code == "0"
    assert updated.review_required is False
    assert "隐式阴性" in (updated.reasoning_summary or "")


def test_implicit_negative_keeps_unknown_when_target_section_is_missing_or_uncertain():
    field = load_field_dictionary().by_key("smoking_history")
    result = extract_field_by_rules(field, [])
    fragments = [
        DocumentFragment(
            page=1,
            reading_order=1,
            text="既往史：高血压病史10年。",
            section_name="既往史",
            block_type="paragraph",
            confidence=0.93,
        )
    ]

    updated = apply_implicit_negative(field, result, fragments, quality_band="good")

    assert updated.normalized_code == "unknown"
