from app.schemas.pipeline import OcrBlock
from app.services.field_dictionary import load_field_dictionary
from app.services.llm_context import build_case_context_for_llm, build_llm_evidence_for_field
from app.services.openai_provider import _build_responses_payload


def test_llm_global_context_prioritizes_field_sections_with_tight_budget():
    field = load_field_dictionary().by_key("smoking_history")
    blocks = [
        OcrBlock(page=1, text=f"无关段落{i}：" + "普通文本" * 8, bbox=[], confidence=0.9)
        for i in range(8)
    ]
    blocks.append(OcrBlock(page=2, text="个人史：否认吸烟，偶尔饮酒。", bbox=[], confidence=0.94))

    evidence = build_llm_evidence_for_field(field, [], blocks)

    assert evidence
    assert "个人史" in evidence[0].text


def test_llm_payload_uses_compact_field_specs_and_shared_case_context():
    dictionary = load_field_dictionary()
    fields = [dictionary.by_key("hypertension_history"), dictionary.by_key("diabetes_history")]
    context = build_case_context_for_llm(
        [
            OcrBlock(page=1, text="既往史：否认高血压，否认糖尿病。", bbox=[], confidence=0.94),
            OcrBlock(page=1, text="个人史：不吸烟，不饮酒。", bbox=[], confidence=0.94),
        ],
        fields=fields,
        budget=500,
    )

    payload = _build_responses_payload(
        case_id="CASE-TOKEN",
        fields=fields,
        evidence_by_field={
            "hypertension_history": [],
            "diabetes_history": [],
            "__case_context__": context,
        },
        model="gpt-5.4-mini",
        prompt_cache_key="cache-key",
    )
    user_text = payload["input"][1]["content"]

    assert "field_specs" in user_text
    assert "case_context" in user_text
    assert "rule_strategy" not in user_text
    assert user_text.count("既往史：否认高血压") == 1
