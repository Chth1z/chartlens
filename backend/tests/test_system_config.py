from app.services.medical_dictionary import terms_for_field
from app.services.system_config import load_system_config


def test_system_config_exposes_accuracy_first_profiles_and_dictionaries():
    config = load_system_config()

    assert config.ocr.default_profile == "accurate"
    assert config.ocr.profiles["fast"].engine_priority[0] == "rapidocr"
    assert config.ocr.profiles["accurate"].pdf_dpi == 300
    assert config.llm.vision_fallback.requires_manual_approval is True
    assert config.evaluation.gold_sample_target_min == 50

    hypertension_terms = terms_for_field("hypertension_history")
    assert "高血压" in hypertension_terms
    assert "血压升高" in hypertension_terms
