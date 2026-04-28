from app.domain.clinical import EvidenceCandidate, OcrBlock
from app.infrastructure.config.field_dictionary import load_field_dictionary
from app.application.llm_context import build_case_context_for_llm, build_llm_evidence_for_field
from app.infrastructure.model.openai_provider import _build_responses_payload


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


def test_llm_payload_orders_cacheable_content_before_dynamic_evidence_and_omits_bboxes():
    dictionary = load_field_dictionary()
    field = dictionary.by_key("surgery_method")
    evidence = [
        OcrBlock(page=3, text="诊疗经过：行支架辅助栓塞术，术后恢复可。", bbox=[1, 2, 3, 4], confidence=0.91),
    ]
    context = build_case_context_for_llm(evidence, fields=[field], budget=500)

    payload = _build_responses_payload(
        case_id="CASE-COMPACT",
        fields=[field],
        evidence_by_field={
            "surgery_method": context,
            "__case_context__": context,
        },
        model="gpt-5.4-mini",
        prompt_cache_key="cache-key",
    )
    user_text = payload["input"][1]["content"]

    assert user_text.index("rules") < user_text.index("case_id")
    assert user_text.index("field_specs") < user_text.index("evidence_by_field")
    assert '"bbox"' not in user_text
    assert '"id"' in user_text


def test_llm_payload_limits_field_evidence_and_omits_unrelated_long_context():
    dictionary = load_field_dictionary()
    field = dictionary.by_key("age")
    evidence_items = [
        EvidenceCandidate(field_key="age", text=f"年龄候选{i}：约六十岁", page=1, bbox=[], ocr_confidence=0.9, score=0.8)
        for i in range(4)
    ]
    context = [
        EvidenceCandidate(
            field_key="__case_context__",
            text="病例摘要：" + "无关长文本" * 300,
            page=6,
            bbox=[],
            ocr_confidence=0.9,
            score=0.2,
        )
    ]

    payload = _build_responses_payload(
        case_id="CASE-LIMITED",
        fields=[field],
        evidence_by_field={"age": evidence_items, "__case_context__": context},
        model="gpt-5.4-mini",
        prompt_cache_key="cache-key",
    )
    user_text = payload["input"][1]["content"]

    assert "年龄候选0" in user_text
    assert "年龄候选1" in user_text
    assert "年龄候选2" not in user_text
    assert user_text.count("无关长文本") < 20
