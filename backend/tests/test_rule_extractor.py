import pytest

from app.domain.clinical import EvidenceCandidate
from app.infrastructure.config.field_dictionary import load_field_dictionary
from app.domain.clinical import DocumentFragment
from app.application.implicit_negative import apply_implicit_negative
from app.application.rule_extractor import compact_evidence_for_llm, extract_field_by_rules, should_escalate_to_llm


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


def test_rules_extract_demographics_from_patient_sentence():
    dictionary = load_field_dictionary()

    gender = extract_field_by_rules(dictionary.by_key("gender"), [candidate("gender", "患者，男，66岁，因头痛入院。")])
    age = extract_field_by_rules(dictionary.by_key("age"), [candidate("age", "患者，男，66岁，因头痛入院。")])

    assert gender.normalized_code == "1"
    assert age.normalized_code == "66"


def test_gender_rule_does_not_match_family_or_patient_description_words():
    field = load_field_dictionary().by_key("gender")

    family_result = extract_field_by_rules(field, [candidate("gender", "婚姻史：已婚，配偶健康状况良好，家庭和睦，已有子女健康。")])
    description_result = extract_field_by_rules(field, [candidate("gender", "病例摘要：患者：小红，老年女性患者，急性病程。")])

    assert family_result.normalized_code == "unknown"
    assert family_result.error_code == "RULE_MISS"
    assert description_result.normalized_code == "unknown"
    assert description_result.error_code == "RULE_MISS"


def test_age_rule_prefers_labelled_homepage_field_and_supports_patient_sentence():
    field = load_field_dictionary().by_key("age")

    labelled = extract_field_by_rules(field, [candidate("age", "年龄：60岁 工作单位：无")])
    patient_sentence = extract_field_by_rules(field, [candidate("age", "患者，女，60岁，因发热10天入院。")])

    assert labelled.normalized_code == "60"
    assert patient_sentence.normalized_code == "60"


def test_history_rule_handles_negation_without_guessing():
    field = load_field_dictionary().by_key("hypertension_history")

    result = extract_field_by_rules(field, [candidate(field.key, "既往史：否认高血压病史，否认糖尿病病史。")])

    assert result.raw_value == "无"
    assert result.normalized_code == "0"
    assert result.evidence_text == "既往史：否认高血压病史，否认糖尿病病史。"
    assert result.review_required is True
    assert result.error_code == "NEGATED_EVIDENCE_REVIEW"


def test_history_rule_marks_same_section_positive_and_negative_conflict():
    field = load_field_dictionary().by_key("hypertension_history")

    result = extract_field_by_rules(
        field,
        [
            candidate(field.key, "既往史：既往有高血压病史10年，本次记录又写否认高血压病史。"),
        ],
    )

    assert result.normalized_code == "unknown"
    assert result.review_required is True
    assert result.error_code == "CONFLICT"


def test_mapping_rule_prefers_specific_surgery_pattern_over_generic_match():
    field = load_field_dictionary().by_key("surgery_method")

    result = extract_field_by_rules(field, [candidate(field.key, "诊疗经过：行支架辅助栓塞术，术后恢复可。")])

    assert result.normalized_code == "支架辅助栓塞术"


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


def test_personal_history_compound_no_smoking_drinking_is_explicit_negative():
    dictionary = load_field_dictionary()
    evidence_text = "个人史：原籍生长，无外地长期居住史，无疫区、疫水接触史，无工业粉尘、毒物、放射性物质接触史，否认冶游史，无烟酒不良嗜好。"

    smoking = extract_field_by_rules(dictionary.by_key("smoking_history"), [candidate("smoking_history", evidence_text)])
    drinking = extract_field_by_rules(dictionary.by_key("drinking_history"), [candidate("drinking_history", evidence_text)])

    assert smoking.normalized_code == "0"
    assert smoking.review_required is False
    assert smoking.error_code is None
    assert "显式阴性" in (smoking.reasoning_summary or "")
    assert drinking.normalized_code == "0"
    assert drinking.review_required is False
    assert drinking.error_code is None
    assert "显式阴性" in (drinking.reasoning_summary or "")


@pytest.mark.parametrize(
    "evidence_text",
    [
        "个人史：无烟酒不良嗜好。",
        "个人史：无烟酒史。",
        "生活史：否认吸烟、饮酒史。",
        "个人史：不吸烟，不饮酒。",
        "个人史：烟酒不沾。",
        "个人史：无不良嗜好。",
    ],
)
def test_personal_history_compound_lifestyle_negative_variants(evidence_text: str):
    dictionary = load_field_dictionary()

    smoking = extract_field_by_rules(dictionary.by_key("smoking_history"), [candidate("smoking_history", evidence_text)])
    drinking = extract_field_by_rules(dictionary.by_key("drinking_history"), [candidate("drinking_history", evidence_text)])

    assert smoking.normalized_code == "0"
    assert smoking.review_required is False
    assert smoking.error_code is None
    assert drinking.normalized_code == "0"
    assert drinking.review_required is False
    assert drinking.error_code is None


def test_lifestyle_negative_pattern_does_not_hide_positive_drinking_history():
    dictionary = load_field_dictionary()
    evidence_text = "个人史：无吸烟，饮酒史10年。"

    drinking = extract_field_by_rules(dictionary.by_key("drinking_history"), [candidate("drinking_history", evidence_text)])

    assert drinking.normalized_code == "1"
    assert drinking.review_required is False


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
