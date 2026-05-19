"""Tests for the LLM-as-judge evidence faithfulness evaluator (M2-002).

These tests verify the judge module's logic without making real LLM calls.
The judge prompt, request building, response parsing, and summary
aggregation are all tested with deterministic inputs.
"""
from __future__ import annotations

from app.domain.models import ValidatedFieldResult
from app.services.eval_judge import (
    build_judge_request,
    judge_field_result,
    parse_judge_response,
    prepare_case_judge_inputs,
    summarize_judge_results,
)


def _make_result(
    field_key: str = "gender",
    normalized_code: str = "1",
    evidence_text: str = "性别：男",
    evidence_block_id: str = "b1",
    **kwargs,
) -> ValidatedFieldResult:
    return ValidatedFieldResult(
        field_key=field_key,
        field_group_key="demographics",
        normalized_code=normalized_code,
        evidence_text=evidence_text,
        evidence_span=evidence_text,
        evidence_block_id=evidence_block_id,
        status="confirmed",
        confidence=0.95,
        review_required=False,
        auto_accepted=True,
        **kwargs,
    )


def test_build_judge_request_includes_all_fields():
    request = build_judge_request(
        field_key="gender",
        normalized_code="1",
        evidence_text="性别：男",
        block_text="基本信息：患者，男，58岁。性别：男",
    )
    assert request["messages"][0]["role"] == "system"
    assert "faithfulness" in request["messages"][0]["content"]
    user_content = request["messages"][1]["content"]
    assert "gender" in user_content
    assert "性别：男" in user_content
    assert request["temperature"] == 0.0
    assert request["response_format"] == {"type": "json_object"}


def test_parse_judge_response_valid_json():
    result = parse_judge_response('{"score": 5, "reason": "Direct match"}')
    assert result["score"] == 5
    assert result["reason"] == "Direct match"


def test_parse_judge_response_with_markdown_fences():
    result = parse_judge_response('```json\n{"score": 3, "reason": "Partial"}\n```')
    assert result["score"] == 3


def test_parse_judge_response_invalid_returns_zero():
    result = parse_judge_response("not json at all")
    assert result["score"] == 0
    assert "parse_failed" in result["reason"]


def test_judge_field_result_skips_unknown():
    result = _make_result(normalized_code="unknown", evidence_text="")
    judge_input = judge_field_result(result, {})
    assert judge_input["skip_reason"] == "unknown_value"
    assert judge_input["score"] == 5
    assert judge_input["request"] is None


def test_judge_field_result_skips_no_evidence():
    result = _make_result(evidence_text="", evidence_block_id="")
    judge_input = judge_field_result(result, {})
    assert judge_input["skip_reason"] == "no_evidence_text"
    assert judge_input["score"] == 1
    assert judge_input["request"] is None


def test_judge_field_result_builds_request_for_valid_evidence():
    result = _make_result()
    blocks = {"b1": "基本信息：患者，男，58岁。性别：男"}
    judge_input = judge_field_result(result, blocks)
    assert judge_input["skip_reason"] is None
    assert judge_input["request"] is not None
    assert judge_input["score"] is None  # Not yet scored


def test_summarize_judge_results_empty():
    summary = summarize_judge_results([])
    assert summary["total_judged"] == 0
    assert summary["mean_score"] == 0.0


def test_summarize_judge_results_with_scores():
    results = [
        {"field_key": "gender", "score": 5, "reason": "perfect", "skip_reason": None, "normalized_code": "1", "evidence_text": "男"},
        {"field_key": "age", "score": 4, "reason": "strong", "skip_reason": None, "normalized_code": "58", "evidence_text": "58岁"},
        {"field_key": "hypertension", "score": 2, "reason": "weak", "skip_reason": None, "normalized_code": "1", "evidence_text": "血压"},
        {"field_key": "diabetes", "score": 5, "reason": "skip", "skip_reason": "unknown_value", "normalized_code": "unknown", "evidence_text": ""},
    ]
    summary = summarize_judge_results(results)
    assert summary["total_judged"] == 4
    assert summary["mean_score"] == 4.0  # (5+4+2+5)/4
    assert summary["low_faithfulness_count"] == 1
    assert summary["low_faithfulness_fields"][0]["field_key"] == "hypertension"


def test_prepare_case_judge_inputs():
    results = [
        _make_result(field_key="gender", normalized_code="1", evidence_text="性别：男"),
        _make_result(field_key="age", normalized_code="58", evidence_text="58岁"),
        _make_result(field_key="unknown_field", normalized_code="unknown", evidence_text=""),
    ]
    doc_ir_json = '{"blocks": [{"block_id": "b1", "text": "性别：男 58岁"}]}'
    inputs = prepare_case_judge_inputs("CASE-001", results, doc_ir_json)
    assert len(inputs) == 3
    # gender and age need LLM calls
    assert inputs[0]["request"] is not None
    assert inputs[1]["request"] is not None
    # unknown is pre-scored
    assert inputs[2]["request"] is None
    assert inputs[2]["score"] == 5
