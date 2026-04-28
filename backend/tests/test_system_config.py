from app.application.medical_dictionary import terms_for_field
from app.infrastructure.config.system_config import load_system_config


def test_system_config_exposes_accuracy_first_profiles_and_dictionaries():
    config = load_system_config()

    assert config.ocr.default_profile == "accurate"
    assert config.ocr.profiles["fast"].engine_priority[0] == "rapidocr"
    assert config.ocr.profiles["accurate"].pdf_dpi == 300
    layout_profile = config.layout.profile("chinese_inpatient_v1")
    assert layout_profile.provider_priority[0] == "pp_structure_v3"
    assert layout_profile.layout_models["fast"] == "PP-DocLayout-S"
    assert layout_profile.layout_models["accurate"] == "PP-DocLayout-M"
    assert config.llm.vision_fallback.requires_manual_approval is True
    assert config.evaluation.gold_sample_target_min == 50

    hypertension_terms = terms_for_field("hypertension_history", config.medical_dictionaries.history_fields)
    assert "高血压" in hypertension_terms
    assert "血压升高" in hypertension_terms
