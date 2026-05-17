import re

from app.core.config_loader import load_document_profile, load_export_template, load_extraction_schema, validate_project_config
from app.domain.models import DocumentKindRule, DocumentProfile
from app.services.domain_profile import document_ai_prompt, document_kind_for_section, extraction_rules, extraction_system_prompt


def test_project_config_is_internally_consistent():
    assert validate_project_config() == []


def test_complex_fields_allow_unknown():
    schema = load_extraction_schema()
    for field in schema.fields:
        if field.extract_mode in {"llm_semantic", "fact_then_code", "computed_from_facts"}:
            assert "unknown" in field.allowed_codes, field.key


def test_export_template_references_existing_fields():
    schema = load_extraction_schema()
    template = load_export_template()
    field_keys = {field.key for field in schema.fields}
    assert all(column.field_key in field_keys for column in template.columns)


def test_medical_export_template_matches_research_headers():
    template = load_export_template()

    assert [column.header for column in template.columns] == [
        "性别(男1，女2)",
        "年龄",
        "医院",
        "是否城市（1非城市2城市）",
        "高血压病史（有1，无0，不详unknown）",
        "糖尿病史（有1，无0，不详unknown）",
        "高血脂病史（有1，无0，不详unknown）",
        "既往心脏疾病分组",
        "卒中分组（有1，无0，不详unknown）",
        "既往肿瘤",
        "是否吸烟",
        "是否饮酒",
        "单发多发",
        "动脉瘤位置（1颈内，2中，3前，4后循环，unknown不详）",
        "HH分组",
        "WFNS分组",
        "Fisher分级",
        "最终手术方式",
        "出现症状到入院前时间",
        "手术距离入院时间",
        "mRS评分",
        "在院死亡",
        "是否转诊",
    ]
    assert template.unknown_value == "unknown"
    assert all(column.unknown_value != "9" for column in template.columns)
    assert template.export_gate.require_pass_or_reviewed is True
    assert template.export_gate.pass_decision_status == "PASS"
    assert "reviewed" in template.export_gate.reviewed_states
    assert "manual_review" in template.export_gate.manual_acceptance_reasons


def test_medical_schema_carries_city_and_timeline_fields():
    schema = load_extraction_schema()

    urban = schema.field_by_key("urban_residence")
    onset_to_admission = schema.field_by_key("onset_to_admission_time")
    admission_to_surgery = schema.field_by_key("admission_to_surgery_time")

    assert urban.allowed_codes == ["1", "2", "unknown"]
    assert urban.pre_redaction_derivations
    assert onset_to_admission.type == "duration"
    assert onset_to_admission.allowed_codes == ["duration", "unknown"]
    assert admission_to_surgery.type == "duration"
    assert admission_to_surgery.allowed_codes == ["duration", "unknown"]


def test_medical_schema_defaults_to_evidence_first_multimodal_policy():
    schema = load_extraction_schema()
    gender = schema.field_by_key("gender")
    diabetes = schema.field_by_key("diabetes_history")
    hospital = schema.field_by_key("hospital")

    assert schema.extraction_strategy == "evidence_first_multimodal"
    assert "diagnosis_inference" in gender.evidence_policy.forbidden_inference_sources
    assert "family_context" in gender.evidence_policy.forbidden_inference_sources
    assert gender.evidence_policy.conflict_policy == "review_conflict"
    assert diabetes.evidence_policy.implicit_negative_policy == "section_complete_only"
    assert hospital.evidence_policy.conflict_policy == "review_conflict"


def test_medical_schema_forbids_remote_full_context_by_default():
    schema = load_extraction_schema()

    assert schema.remote_exposure_policy.allow_full_document_context is False
    assert schema.remote_exposure_policy.allow_page_images is False
    assert schema.remote_exposure_policy.allow_raw_block_text is False
    assert schema.remote_exposure_policy.allow_safe_evidence_candidates is True


def test_document_profile_carries_domain_hooks():
    profile = load_document_profile()

    assert profile.default_document_kind == "admission_note"
    assert any(rule.kind == "operation_note" and "手术记录" in rule.sections for rule in profile.document_kind_rules)
    assert profile.extraction_system_prompt
    assert profile.extraction_rules
    assert any(pattern.blocks_online_llm for pattern in profile.phi_patterns)


def test_medical_profile_handles_screen_captured_course_and_operation_notes():
    profile = load_document_profile()

    assert profile.layout_normalization.enabled is True
    assert profile.layout_normalization.remove_screen_chrome is True
    assert any("保存" in pattern for pattern in profile.layout_normalization.screen_chrome_patterns)
    assert profile.layout_normalization.default_body_region == "clinical_body"
    assert any(rule.region == "signature" for rule in profile.layout_normalization.region_rules)
    assert any(rule.region == "institution_header" for rule in profile.layout_normalization.region_rules)
    assert profile.layout_normalization.derive_key_value_blocks is True
    assert profile.layout_normalization.derive_neighbor_key_value_blocks is True
    assert profile.layout_normalization.key_value_neighbor_max_gap > profile.layout_normalization.merge_horizontal_gap
    assert {"姓名", "性别", "年龄", "床号", "病案号"}.issubset(profile.layout_normalization.key_value_labels)
    assert {"首次病程记录", "日常病程记录", "上级医师首次查房病程记录", "查房记录"}.issubset(
        set(profile.section_aliases["病程记录"])
    )
    assert {"诊断依据", "鉴别诊断", "病情评估", "诊疗计划"}.issubset(profile.section_aliases)
    assert {"手术日期", "术前诊断", "术中诊断", "手术名称", "手术经过", "输血反应"}.issubset(
        set(profile.section_aliases["手术记录"])
    )
    assert "毒物分析" in profile.section_aliases["辅助检查"]
    assert "腹部增强CT" in profile.section_aliases["辅助检查"]
    assert "床号" in profile.excluded_phi_labels
    assert "床号" in profile.phi_inline_labels
    assert "Word标尺" in profile.document_ai_prompt
    assert "窗口标签" in profile.document_ai_prompt
    assert "非病历界面" in profile.document_ai_prompt


def test_medical_profile_prompt_and_rules_require_table_and_paragraph_grounding():
    profile = load_document_profile()

    assert any("表头" in rule and "单元格" in rule for rule in profile.extraction_rules)
    assert any("跨行段落" in rule and "reading_order" in rule for rule in profile.extraction_rules)
    assert "row_header" in profile.document_ai_prompt
    assert "column_header" in profile.document_ai_prompt
    assert "paragraph_id" in profile.document_ai_prompt


def test_high_risk_demographics_reject_non_patient_layout_regions():
    schema = load_extraction_schema()
    fields = {field.key: field for field in schema.fields}

    for key in ("gender", "age", "hospital"):
        policy = fields[key].evidence_policy
        assert "signature" in policy.forbidden_document_regions
        assert "document_footer" in policy.forbidden_document_regions


def test_medical_schema_accepts_header_age_and_common_admission_duration_phrasing():
    schema = load_extraction_schema()

    age_patterns = [rule.pattern for rule in schema.field_by_key("age").rule_patterns]
    assert any(re.search(pattern, "年龄：16") for pattern in age_patterns)

    onset_patterns = schema.field_by_key("onset_to_admission_time").rule_patterns
    examples = [
        "主因服用药物12小时，头晕9小时于2026年03月05日09时11分入院。",
        "查体发现胆囊肿物6天于2026年01月06日08时28分入院。",
        "服药后12小时入院。",
    ]
    for text in examples:
        assert any(re.search(rule.pattern, text) for rule in onset_patterns), text

    surgery_patterns = [rule.pattern for rule in schema.field_by_key("admission_to_surgery_time").rule_patterns]
    assert any(re.search(pattern, "入院第6天行手术治疗") for pattern in surgery_patterns)


def test_domain_profile_uses_profile_configuration_directly():
    profile = DocumentProfile(
        profile_id="invoice_demo",
        label="Invoice Demo",
        section_aliases={"Invoice": ["Invoice"]},
        default_document_kind="business_document",
        document_kind_rules=[DocumentKindRule(kind="invoice", sections=["Invoice"])],
        extraction_system_prompt="Extract invoice fields.",
        extraction_rules=["Use only invoice evidence."],
        document_ai_prompt="Extract invoice OCR blocks.",
    )

    assert document_kind_for_section("Invoice", profile) == "invoice"
    assert extraction_system_prompt(profile) == "Extract invoice fields."
    assert extraction_rules(profile) == ["Use only invoice evidence."]
    assert document_ai_prompt(profile) == "Extract invoice OCR blocks."
