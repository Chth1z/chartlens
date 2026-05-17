"""Tests pinning the evidence-first system prompt content.

E1-001 prompt rewrite (2026-05-18) introduced explicit guidance on:
1. evidence binding (block_id, page, verbatim evidence_text);
2. field-level evidence_policy as the authoritative contract;
3. section-complete implicit-negative semantics ('既往史：无特殊' etc);
4. clause-bounded negation;
5. allowed_codes as the only valid normalized_code set.

These tests pin the prompt structure so a future change cannot
silently regress the 4 LLM baseline failures on eval-mock-007 that
this rewrite closed (mock_general_llm baseline accuracy 0.9259 → 1.0,
input tokens 72372 → 37792). They do not call any LLM; they only
inspect the prompt string.
"""
from __future__ import annotations

from app.domain.models import DocumentContext
from app.services.llm_provider.cache import EVIDENCE_FIRST_PROMPT_VERSION
from app.services.llm_provider.payloads import _evidence_first_system_prompt


def _empty_context() -> DocumentContext:
    return DocumentContext(
        document_id="prompt-test",
        profile_id="medical_inpatient_zh",
        source_filename="prompt-test.txt",
        pages=[],
        metadata={},
    )


def test_prompt_version_bumped_for_e1_001_rewrite():
    """Prompt rewrite must bump the version so cache keys invalidate
    automatically. Anyone changing the prompt text should also bump
    this version in cache.py; the LLM result cache uses this string in
    its hash material."""
    assert EVIDENCE_FIRST_PROMPT_VERSION == "eyex-evidence-first-v2"


def test_prompt_documents_section_complete_implicit_negative():
    """The medical-history baseline failure on eval-mock-007 (`既往史：
    无特殊`) was caused by the LLM not knowing that this pattern counts
    as a section-complete implicit-negative under the field policy. The
    rewrite must surface that pattern in the cacheable prefix."""
    prompt = _evidence_first_system_prompt(_empty_context())
    assert "implicit_negative_policy" in prompt
    assert "section_complete_only" in prompt
    assert "既往史：无特殊" in prompt
    assert "未见异常" in prompt or "无明显异常" in prompt


def test_prompt_promotes_field_policy_over_generic_rules():
    """The previous prompt put the generic 'missing means unknown' rule
    above field-level policy. The rewrite must promote field-level
    policy first so that cases where the schema explicitly enables
    section-complete implicit-negative are not overridden by the
    generic safe-unknown default."""
    prompt = _evidence_first_system_prompt(_empty_context())
    # Both phrases must be present, but the field-policy block must
    # come before the generic-rules block so the model reads policy
    # first when scanning the prompt.
    field_policy_idx = prompt.find("字段证据政策优先")
    generic_idx = prompt.find("通用规则")
    assert field_policy_idx >= 0, "prompt must contain field-policy block"
    assert generic_idx >= 0, "prompt must contain generic-rules block"
    assert field_policy_idx < generic_idx, (
        "field-policy block must precede generic-rules block; this is the "
        "specific structural change that closed the eval-mock-007 baseline gap"
    )


def test_prompt_warns_against_family_context_inference():
    """forbidden_inference_flags / family_context guidance must remain
    so that fixtures like eval-mock-007 (family-history paragraph
    mentions 高血压病、糖尿病、冠心病) do not leak into patient fields."""
    prompt = _evidence_first_system_prompt(_empty_context())
    assert "family_context" in prompt
    assert "forbidden_inference_flags" in prompt


def test_prompt_pins_clause_bounded_negation():
    """The 2026-05-17 clause-boundary fix in _positive_span requires
    the LLM to also respect clause boundaries when reading negation.
    Otherwise the LLM might reintroduce the `否认A、B 后跟 C 阳性 → C 错判否定`
    failure that the rule path already fixed."""
    prompt = _evidence_first_system_prompt(_empty_context())
    assert "否定句的范围只到本子句末尾" in prompt or "clause" in prompt.lower()


def test_prompt_locks_normalized_code_to_allowed_codes():
    """Models tend to invent 'unsure' or 'low' codes when the schema
    only allows '0' / '1' / 'unknown'. The prompt must explicitly
    say only allowed_codes are valid."""
    prompt = _evidence_first_system_prompt(_empty_context())
    assert "allowed_codes" in prompt


def test_prompt_does_not_contain_per_case_data():
    """DeepSeek prompt-cache hits require the system prompt prefix to
    be byte-stable across cases. The prompt must not interpolate any
    document_id, case_id, or fixture content."""
    prompt = _evidence_first_system_prompt(_empty_context())
    assert "prompt-test" not in prompt  # the document_id from the empty context
    assert "case_id" not in prompt.lower() or "case_id 必须" not in prompt
    # No timestamps, no random hashes — we look for a few suspicious
    # tokens that would change per call.
    for marker in ("uuid", "timestamp", "now()", "random"):
        assert marker not in prompt.lower(), (
            f"prompt contained '{marker}' which would break cache stability"
        )


def test_prompt_is_byte_stable_across_calls():
    """A second invocation with the same document_context must produce
    the identical string. Without this guarantee, DeepSeek prompt-cache
    hits would never accumulate."""
    ctx = _empty_context()
    first = _evidence_first_system_prompt(ctx)
    second = _evidence_first_system_prompt(ctx)
    assert first == second
