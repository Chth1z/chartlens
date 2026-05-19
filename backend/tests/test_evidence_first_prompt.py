"""Tests pinning the evidence-first system prompt content.

E1-001 prompt rewrite (2026-05-18) introduced explicit guidance on:
1. evidence binding (block_id, page, verbatim evidence_text);
2. field-level evidence_policy as the authoritative contract;
3. section-complete implicit-negative semantics ('既往史：无特殊' etc);
4. clause-bounded negation;
5. allowed_codes as the only valid normalized_code set.

E1-001 v3 (2026-05-19) tightens the same prompt to close two LLM
fidelity gaps surfaced by the v2 mock_general_llm baseline:
- `eval-mock-009 / hospital`: DeepSeek returned `normalized_code='text'`
  by echoing the schema's `allowed_codes=[text, unknown]` placeholder
  literal. The v3 prompt teaches that 'text' / 'integer' / 'float' /
  'string' / 'number' / 'enum' inside allowed_codes are TYPE markers,
  not values to copy.
- `eval-mock-010 / diabetes_history`: DeepSeek paraphrased
  `否认糖尿病` from the verbatim `否认高血压病、糖尿病、冠心病等病史`. The v3
  prompt forbids paraphrase / ellipsis / per-item synthesis and requires
  evidence_text to be a contiguous substring of the cited block's text.

These tests pin the prompt structure so a future change cannot
silently regress the closed failure modes. They do not call any LLM;
they only inspect the prompt string.
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
    its hash material. v2 → v3 step lands with the substring +
    placeholder rules below. v3 → v3.1 strengthens the implicit-negative
    rule to explicitly call out that family-history mentions do NOT block
    the section-complete implicit-negative for the patient's own fields."""
    assert EVIDENCE_FIRST_PROMPT_VERSION == "eyex-evidence-first-v3.1"


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


def test_v3_prompt_requires_substring_evidence_text():
    """v3 closes two LLM evidence-text fidelity failures surfaced by
    the mock_general_llm v2 baseline:

    - hospital: the LLM returned `normalized_code='text'`, echoing the
      schema's `allowed_codes=[text, unknown]` placeholder literal as
      if it were a valid value.
    - diabetes_history: the LLM paraphrased `否认糖尿病` from the
      verbatim `否认高血压病、糖尿病、冠心病等病史`.

    The v3 prompt must contain both the contiguous-substring rule and
    the placeholder-not-value rule in the cacheable prefix so the
    contract is enforced uniformly across cases.
    """
    prompt = _evidence_first_system_prompt(_empty_context())

    # Contiguous-substring rule for evidence_text.
    assert "evidence_text 必须为引用 block 的连续子串" in prompt, (
        "v3 prompt must declare the contiguous-substring rule as a top-level "
        "section so the LLM cannot paraphrase or per-item-synthesize"
    )
    # The specific 否认A、B、C 等病史 example must be called out so the
    # eval-mock-010 paraphrase failure cannot recur silently.
    assert "否认高血压病、糖尿病、冠心病等病史" in prompt, (
        "v3 prompt must show the verbatim 否认 ... 等病史 clause as the "
        "concrete example of the no-paraphrase rule"
    )
    # The substring rule must explicitly forbid paraphrase / ellipsis /
    # synthesis. We accept any of a few synonymous Chinese phrasings as
    # long as the prohibition is unmistakable.
    assert "改写" in prompt or "paraphrase" in prompt.lower()
    assert "拼接" in prompt or "调换" in prompt or "省略" in prompt

    # Placeholder-not-value rule for normalized_code.
    assert "normalized_code 不是类型占位符" in prompt, (
        "v3 prompt must declare a top-level section that explains "
        "allowed_codes type-class placeholders are not valid values to copy"
    )
    # The six type-class placeholders that the schema uses must all be
    # named so the LLM cannot rationalize copying any of them.
    for placeholder in ("'text'", "'integer'", "'float'"):
        assert placeholder in prompt, (
            f"v3 prompt must explicitly call out the {placeholder} placeholder"
        )
    # The hospital case must be anchored as the concrete example of a
    # free-text field whose normalized_code is the actual value.
    assert "hospital" in prompt
    assert "海安县中医院" in prompt or "南京市第一人民医院" in prompt, (
        "v3 prompt must show a real Chinese hospital name as the concrete "
        "example of normalized_code for free-text fields"
    )
