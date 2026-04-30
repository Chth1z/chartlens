from app.core.config_loader import load_document_profile, load_export_template, load_extraction_schema, validate_project_config


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


def test_document_profile_carries_domain_hooks():
    profile = load_document_profile()

    assert profile.default_document_kind == "admission_note"
    assert any(rule.kind == "operation_note" and "手术记录" in rule.sections for rule in profile.document_kind_rules)
    assert profile.extraction_system_prompt
    assert profile.extraction_rules
    assert any(pattern.blocks_online_llm for pattern in profile.phi_patterns)
