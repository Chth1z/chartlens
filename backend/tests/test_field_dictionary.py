from app.services.field_dictionary import load_field_dictionary


def test_field_dictionary_contains_mvp_core_fields():
    dictionary = load_field_dictionary()
    keys = {field.key for field in dictionary.fields}

    assert {
        "gender",
        "age",
        "hospital",
        "hypertension_history",
        "diabetes_history",
        "hyperlipidemia_history",
        "heart_disease_history",
        "stroke_history",
        "tumor_history",
        "smoking_history",
        "drinking_history",
        "surgery_method",
        "in_hospital_death",
        "transfer",
    }.issubset(keys)


def test_field_dictionary_validates_allowed_codes():
    dictionary = load_field_dictionary()
    gender = dictionary.by_key("gender")
    hypertension = dictionary.by_key("hypertension_history")

    assert gender.allowed_codes == ["1", "2", "unknown"]
    assert hypertension.allowed_codes == ["1", "0", "unknown"]


def test_field_dictionary_drives_rules_and_llm_policy_from_yaml():
    dictionary = load_field_dictionary()
    gender = dictionary.by_key("gender")
    age = dictionary.by_key("age")

    assert gender.rule_strategy["kind"] == "regex"
    assert gender.llm.enabled is False
    assert age.llm.enabled is True
    assert "missing" in age.llm.trigger_statuses
    assert age.llm.evidence_budget > 0
