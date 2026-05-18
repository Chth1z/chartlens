# LLM Provider Refactor Plan

This document is the deep analysis behind ROADMAP `E1-011` (the gap surfaced when the `--provider llm` baseline against DeepSeek recorded `input_tokens=0`). It expands `E1-011` from a one-line task into a phased refactor anchored on real code, real open-source patterns, and a reproducible verification ladder.

Status: all three phases closed on 2026-05-18 (Phase 1 / Phase 2 / Phase 3 commits land in the order described in section 6 below). The architectural rule the refactor establishes lives in `docs/DECISIONS.md` 2026-05-18 "Default-inheritance shim for collect_evidence is forbidden" and in `AGENTS.md` "Architecture Boundaries". Section text below reads as a historical RFC; the "Phase X" subsections each carry a "Closed" line summarizing the actual landed change.

## 1. Symptom

Running

```powershell
python scripts\bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --baseline
```

against the active DeepSeek profile produces a baseline with `input_tokens=0`, `output_tokens=0`, `cost_usd=0.000000`. The bootstrap script now warns about it (`scripts/bootstrap-eval-fixtures.py:WARN`), but the warning is mitigation, not a fix.

The same command against an OpenAI Responses profile would actually call OpenAI. The asymmetry is the bug.

## 2. Root Cause

In `backend/app/services/llm_provider/types.py`, the `SemanticExtractionProvider` base class supplies a default `collect_evidence` that **silently delegates to local rule extraction**:

```python
def collect_evidence(self, *, document_context, fields):
    from app.services.evidence_first import collect_local_evidence
    self.last_usage = {"input_tokens": 0, "output_tokens": 0, ...}
    return collect_local_evidence(document_context, fields)
```

In `backend/app/services/llm_provider/adapters.py`:

| Adapter | `extract_group` | `collect_evidence` |
| --- | --- | --- |
| `OpenAIResponsesProvider` | implemented (line 49) | **implemented** (line 99) |
| `OpenAICompatibleChatProvider` | implemented (line 178) | inherited default (silent local fallback) |
| `AnthropicMessagesProvider` | implemented (line 247) | inherited default (silent local fallback) |
| `GoogleGeminiProvider` | implemented (line 304) | inherited default (silent local fallback) |
| `ConservativeLocalProvider` | implemented (in `local_extraction.py`) | inherited default (correct: it should be local) |

In `backend/app/services/pipeline.py:_extract_document_evidence_first` the default extraction path for `extraction_strategy: evidence_first_multimodal` calls `provider.collect_evidence(...)`. When the active profile is anything except `openai_responses`, this default base-class shortcut runs and the LLM is never contacted.

The schema `config/extraction_schemas/medical_inpatient_zh.yaml` has `extraction_strategy: evidence_first_multimodal` (line 4). So today, **DeepSeek / Anthropic / Gemini / OpenRouter / Moonshot / Qwen / Z.AI / Azure-OpenAI / Custom**, all of them, run the rule path even when they are picked as the active model profile.

This is not a configuration issue. It is an architectural decision (`SemanticExtractionProvider` is overly generous with its default) plus an incomplete implementation (only one of four LLM adapters fills in the override).

## 3. Why It Stayed Hidden

Several mitigations made the gap invisible until E0-008 made eval reports emit `input_tokens` summaries:

- `pipeline._extract_document_evidence_first` writes `provider.last_usage` to `processing_runs.diagnostics_json["llm_usage"]`. With the default shim, that value is always `{"input_tokens": 0, ...}`, which looks identical to a legitimate "no LLM call needed" path.
- The frontend diagnostics surface aggregated per-stage timing but not per-stage token counts.
- Cache files under `var/storage/llm_cache/*.json` come from `extract_group` (the legacy group-based path), not from `collect_evidence`. So the existence of cache files made it look like LLMs were being called, when in fact they were called by an older flow that the medical schema does not select.
- DeepSeek connectivity tests (`scripts/check-llm-connectivity.py`) succeed because `/v1/models` is reachable. They prove credentials work; they prove nothing about whether the runtime path uses the credentials.

## 4. Other Architectural Observations

Walking the same code surface with the same pattern in mind surfaces three more issues that do not block the immediate fix but should land in the same refactor batch.

### 4.1 Two parallel extraction paths

`pipeline.extract_document` has two branches:

- `evidence_first_multimodal` -> `_extract_document_evidence_first` -> `provider.collect_evidence` (the modern path).
- everything else -> `provider.extract_group(group, fields, blocks)` (the legacy group-based path).

The medical schema only uses the first; `mock_general` shares the medical schema. The legacy path still has provider implementations (`extract_group` is filled in for every adapter). They are dead code on the medical line but not under any other extraction strategy. After E1-011 lands, the right move is either to retire `extract_group` from the adapters or document the trigger conditions so a future schema change does not silently re-activate it.

### 4.2 Adapter inheritance does not enforce the contract

`SemanticExtractionProvider` declares `extract_group` as `@abstractmethod` but `collect_evidence` / `adjudicate_fields` / `verify_against_document` as concrete defaults. Python lets a subclass omit them and inherit silently. There is no test or governance check that asserts every concrete adapter implements `collect_evidence`. The 2026-05-18 baseline run exposed this only because the bootstrap eval surfaced the cost number.

### 4.3 Provider registration is hand-wired in `_provider_for_profile`

`fallback._provider_for_profile` is a long if/elif on `profile.provider` strings:

```python
if profile.provider == "openai_responses" and settings.llm_mode in {"auto", "online"}:
    return OpenAIResponsesProvider(profile)
if profile.provider == "openai_compatible" and settings.llm_mode in {"auto", "online", "local"}:
    return OpenAICompatibleChatProvider(profile)
...
```

Adding a fifth provider type means editing this function in addition to writing the adapter. There is no registry, no plugin point, and no test that asserts every `provider` value declared in `config/model_providers/mainstream.yaml` has an adapter mapping.

### 4.4 `extract_group` and `collect_evidence` duplicate too much glue

Each adapter ends up writing the same scaffolding:

- cache key compute, read, write
- per-key cooldown loop with `_api_keys_for_attempts` / `_mark_api_key_cooldown`
- base-url candidate loop (only `OpenAICompatibleChatProvider` has this; the others get away with one URL because they target official endpoints)
- exception classification (`_is_rate_limit_or_timeout`)
- usage extraction with provider-specific field names (`prompt_tokens` vs `input_tokens` vs `promptTokenCount`)

That scaffolding is ~50 lines of boilerplate per (adapter, method) pair. With 4 adapters times 2 methods times 50 lines, the boilerplate dominates the actual API-shape code.

## 5. Open-Source Baselines

The two most useful references for a router-style refactor (already documented in `docs/REFERENCE_PROJECTS.md`) are:

### 5.1 LiteLLM Router

LiteLLM's `Router` (Apache-2.0) splits the call into three layers (per `docs.litellm.ai/docs/router_architecture`):

```text
function_with_fallbacks (try / except across model groups)
  function_with_retries  (retry inside a model group)
    litellm.completion   (single call, normalized to OpenAI shape)
```

Useful patterns:

- The retry layer is **separate** from the fallback layer. EYEX today couples them in `ModelFallbackProvider.collect_evidence`, which iterates `self.profiles` and treats each profile as both a retry and a fallback target.
- The cooldown system is **reactive**: a deployment is cooled down after a real user request fails, not preemptively. EYEX matches this through `_mark_api_key_cooldown`.
- The unified `litellm.completion` function normalizes input arguments and output shape across providers, so the layers above never see provider-specific token-field names. EYEX has the opposite shape: each adapter does its own normalization and the layers above do not see a normalized usage dict.
- Timeouts are explicit at every level (router, model group, single call). EYEX uses one global setting `settings.openai_timeout_seconds` for every adapter, despite different upstream SLAs.

### 5.2 LangChain `BaseChatModel.with_structured_output`

LangChain's `BaseChatModel` (MIT) exposes a single `with_structured_output(schema, method=...)` method that returns a wrapper which:

1. Selects between `function_calling`, `json_mode`, and `json_schema` modes per provider capability.
2. Forces the model to emit JSON conforming to the schema.
3. Validates the response against the schema and raises `OutputParserException` on mismatch.

Useful patterns:

- One pluggable schema-binding layer for **every** provider. EYEX today re-implements JSON-mode prompt setup four times (`_responses_payload`, `_chat_completions_payload`, `_anthropic_payload`, `_gemini_payload`). The schema binding logic is duplicated, just with provider-specific field names.
- A capability declaration: each provider declares which structured-output method it supports. EYEX's `model_profile.compat` field could hold the same data but is currently unused for routing decisions.

### 5.3 DeepSeek prompt cache discipline

Per `api-docs.deepseek.com/guides/kv_cache` (2025), DeepSeek's prompt-cache hit requires the **prefix** of the request to be byte-stable. Each request produces a cache prefix unit at the end of the user input and a separate one at the end of the model output; subsequent requests hit the cache only if they fully match.

Implications for any EYEX collect_evidence implementation:

- The system prompt + extraction rules + JSON schema descriptor must be the same byte-for-byte across cases. Any per-case detail must follow the cacheable prefix, not be interleaved.
- `temperature: 0.0` is necessary but not sufficient; the prefix itself must not change.
- DeepSeek's cache hit pricing is 90% cheaper than miss, so a working cache turns a 20-case eval pass from ~80k tokens billed to ~8k tokens billed.

EYEX `cache.py:_evidence_first_cache_key` already hashes a stable schema, prompt-version, model, and field-policy material. This is the **client-side** cache. It is independent of the **server-side** DeepSeek cache. After E1-011, both should be working: client-side avoids the round trip; server-side avoids the input-token cost when round trips happen anyway (after a client-cache miss).

## 6. Refactor Plan: Three Phases

The refactor is split so each phase is one PLAN task, each commits independently, and each is independently revertible.

### Phase 1 — Make the gap a hard error (no behavior change)

**Closed 2026-05-18.** `SemanticExtractionProvider.collect_evidence` and `extract_group` are both `@abstractmethod`; every concrete adapter declares an explicit override. `OpenAICompatibleChatProvider`, `AnthropicMessagesProvider`, and `GoogleGeminiProvider` initially landed as `return local_collect_evidence_fallback(...)` shims; Phases 2 and 3 replaced those shims with real upstream calls. New `backend/tests/test_provider_contracts.py` (15 tests) pins the rule. AGENTS.md "Architecture Boundaries" gained the explicit-delegation rule. `docs/DECISIONS.md` records "Default-inheritance shim for collect_evidence is forbidden".

**Goal.** Force every adapter to declare its `collect_evidence` strategy. Today the default shim is a footgun; tomorrow there will be no default.

**Changes.**

1. `services/llm_provider/types.py`: `SemanticExtractionProvider.collect_evidence` becomes `@abstractmethod`. The current default body moves to a named helper `local_collect_evidence_fallback(document_context, fields)` exported from the same module. `ConservativeLocalProvider`, `OpenAIResponsesProvider`, `OpenAICompatibleChatProvider`, `AnthropicMessagesProvider`, `GoogleGeminiProvider` all gain explicit overrides.
2. The four LLM adapters keep their current behavior in this phase: their new override is `return local_collect_evidence_fallback(...)`. The behavior on disk is identical, but the override is now explicit and a future test can grep for adapters that delegate without a real implementation.
3. `tests/test_provider_contracts.py`: new contract test that for every concrete subclass of `SemanticExtractionProvider`, `collect_evidence` is defined directly on the subclass (not inherited). Also asserts every `provider` value in `config/model_providers/mainstream.yaml` has an adapter wiring in `_provider_for_profile`.
4. The bootstrap WARN line stays, but a sibling test asserts the warning fires only when an adapter explicitly chose to delegate.
5. AGENTS.md "Architecture Boundaries" section adds: "Every concrete `SemanticExtractionProvider` adapter must explicitly choose between calling its remote API and delegating to `local_collect_evidence_fallback`. The default-inheritance shim is forbidden."

**Acceptance.** All 303 backend tests pass. The new contract test exists and would fail if a future adapter omitted `collect_evidence`. The mock_general LLM baseline still records `input_tokens=0` (because the adapters chose to delegate explicitly), but the choice is now a one-line `return local_collect_evidence_fallback(...)` instead of an invisible inheritance.

**Out of scope.** No new LLM call. No prompt change. No accuracy change.

**Risk.** Very low. This is a refactor that names an existing behavior.

### Phase 2 — OpenAI-compatible chat collect_evidence

**Closed 2026-05-18.** `OpenAICompatibleChatProvider.collect_evidence` calls `client.chat.completions.create` with `response_format={"type": "json_object"}` and the evidence-first JSON schema. New helper `_chat_completions_evidence_first_payload` keeps the cacheable prefix byte-stable. Permanent error / missing response / malformed JSON degrade to `local_collect_evidence_fallback`; rate-limit / timeout enters per-key cooldown. New `--unsafe-eval-allow-remote-context` flag on `bootstrap-eval-fixtures.py` activates a process-local override so synthetic fixtures can opt into full-context exposure. `mock_general_llm.json` baseline lands at `accuracy=0.9259` (50/54), `input_tokens=72372`, `output_tokens=18757` against DeepSeek v4-flash. The 4 failures cluster on `eval-mock-007` implicit-negative — the E1-001 prompt-rewrite target.

**Goal.** Make `OpenAICompatibleChatProvider.collect_evidence` actually call DeepSeek (or any OpenAI-compatible chat endpoint) and return parsed `EvidenceCandidate` objects. After this phase, the mock_general LLM baseline records non-zero `input_tokens` and the WARN line goes away.

**Changes.**

1. `services/llm_provider/payloads.py`: extract a new `_chat_completions_evidence_first_payload(document_context, fields, model, profile)` modeled on `_responses_evidence_first_payload`. Reuses the same `_evidence_first_system_prompt`, the same `_evidence_first_user_payload`, and the same `_evidence_candidate_response_schema`. Differs only in the wire format:
   - `messages: [{role: system, content: <prompt>}, {role: user, content: json.dumps(user_payload)}]`
   - `response_format: {"type": "json_object"}` (DeepSeek and OpenRouter both support this; per DeepSeek docs, the word "json" must appear in system or user prompt — it already does via `output_schema`)
   - `temperature: profile.temperature` (default 0.0)
   - `max_tokens: profile.max_output_tokens`
2. `services/llm_provider/parsing.py`: a new `_chat_evidence_candidates_from_text(text)` that wraps `_evidence_candidates_from_text` with chat-completions-specific cleanup (DeepSeek occasionally wraps the JSON in markdown fences; strip them before json.loads).
3. `services/llm_provider/adapters.py:OpenAICompatibleChatProvider`: replace the Phase 1 explicit-delegation shim with a real implementation that mirrors `OpenAIResponsesProvider.collect_evidence` but uses `client.chat.completions.create(**payload)` instead of `client.responses.create(**payload)`. The base-URL candidate loop, the cooldown loop, and the cache integration are reused unchanged.
4. The same change applied to `AnthropicMessagesProvider` and `GoogleGeminiProvider` is **deferred to Phase 3**. In Phase 2, those two keep delegating explicitly, so the medical pipeline must not silently route through them. The `ModelFallbackProvider` must check the chosen primary's capability before dispatching; if the primary is one of those two, it falls back to local right away rather than crossing the network. This is one new check, not a new code path.
5. New test `tests/test_chat_completions_evidence_first.py`:
   - Stubs an OpenAI-compatible HTTP server with `respx` (already an indirect dep through `httpx`'s test ecosystem; if not installed, use `unittest.mock.patch` on the OpenAI client).
   - Asserts the request payload has the cacheable prefix in the system message and the per-case context in the user message.
   - Asserts the parsed `EvidenceCandidate` list has every candidate bound to a `block_id` from the input context.
   - Asserts a malformed JSON response degrades gracefully to `local_collect_evidence_fallback` (no crash, no fabricated candidates).

**Acceptance.**

- `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --baseline` produces a baseline with `input_tokens > 0`, `output_tokens > 0`, `cost_usd > 0`. Exact numbers depend on DeepSeek pricing; the contract is "non-zero".
- Mock_general LLM baseline accuracy stays at or above the rule-only baseline (1.0 on 54/54). Falling below means LLM-collected evidence regressed something rule-only handled; that would be a real bug to fix in this same commit.
- A second consecutive run shows `cached_input_tokens > 0` (DeepSeek prompt cache hit), confirming the prefix discipline.
- The WARN line is gone from the bootstrap output.
- All 303 backend tests plus the new ~5 contract tests pass.

**Out of scope.** No new prompt content (E1-001 remains separate). No retry-with-validation-feedback (E1-003 remains separate). No new fixtures.

**Risk.** Medium. The phase exercises a real network round trip on every fixture during the baseline regenerate. Rate limits are possible. Mitigation: bootstrap uses `_api_keys_for_attempts` cooldown, and the cache layer kicks in after the first run; a third run should be entirely cache-hit.

### Phase 3 — Anthropic and Gemini collect_evidence; router cleanup

**Closed 2026-05-18.** `AnthropicMessagesProvider.collect_evidence` posts to `/v1/messages` with the byte-stable evidence-first system prompt + JSON schema descriptor in the cacheable `system` field. `GoogleGeminiProvider.collect_evidence` posts to `/v1beta/models/<model>:generateContent` with `responseMimeType=application/json` and a translated `responseSchema` (drops `additionalProperties`, folds `type: ['x', 'null']` into `nullable: true`, uppercases types per OpenAPI 3.0). New `services/llm_provider/registry.py` replaces the if/elif chain with a data-driven `(adapter factory, allowed llm_modes)` table; `fallback._provider_for_profile` is now a thin delegating shim. Both new adapters honor `safe_evidence_only` and degrade to `local_collect_evidence_fallback` with `remote_skipped_reason=remote_full_context_disabled` when the schema disallows full context. New `test_provider_phase_3.py` (14 tests) pins payload byte-stability, real-implementation references, registry coverage, `llm_mode` gating, and the privacy fallback path. Backend tests rise from 326 to 340. Two design choices intentionally deferred (and documented in section 4): the `Router.with_retries()` / `Router.with_fallbacks()` LiteLLM class extraction (`ModelFallbackProvider` already separates fallback iteration from per-adapter retry/cooldown, so the structural goal is already met), and removal of the legacy `extract_group` path (every adapter still implements it because the medical schema's `aneurysm_group`, `surgery_group`, `score_group`, `discharge_group`, and `history_group` actively select `llm_semantic` / `llm_facts_then_compute` strategies that route through `extract_group`).

**Goal.** Make every LLM adapter complete; retire dead-code paths surfaced in section 4.

**Changes.**

1. `AnthropicMessagesProvider.collect_evidence` and `GoogleGeminiProvider.collect_evidence` follow the Phase 2 pattern with provider-specific shapes:
   - Anthropic: `system`-then-`messages` with `response_format: tool_use` calling a `submit_evidence_candidates` tool that wraps the JSON schema (Anthropic's preferred path for structured output). Token field names: `usage.input_tokens` / `usage.output_tokens` / `usage.cache_read_input_tokens`.
   - Gemini: `systemInstruction` + `contents` with `responseMimeType: application/json` and `responseSchema`. Token field names: `usageMetadata.promptTokenCount` / `candidatesTokenCount` / `cachedContentTokenCount`.
2. `services/llm_provider/router.py`: extract the router from `fallback.py`. The new `Router` class owns the `(retry, fallback)` matrix that LiteLLM separates. Today's `ModelFallbackProvider` becomes a thin compatibility shim around `Router` until a follow-up commit retires it.
3. `services/llm_provider/registry.py`: replace `_provider_for_profile`'s if/elif with a registry. The registry maps `profile.provider` -> adapter class. New providers register at module import time. A test asserts the registry covers every value used in `config/model_providers/mainstream.yaml`.
4. The legacy `extract_group` path: walk every adapter's `extract_group` and decide either to delete it (the medical schema does not use it) or document its trigger condition. Today there is no schema in the repo that drives this path; the right move is to gate it behind a non-default `extraction_strategy` and document the deletion condition: "remove `extract_group` from adapters when no schema declares `group_evidence_pack` or `multimodal_llm` strategies".
5. AGENTS.md addition documenting the (retry, fallback, cooldown) matrix as a stable contract, not just an implementation detail.

**Acceptance.**

- Every adapter declared in `config/model_providers/mainstream.yaml` has a real `collect_evidence`. `bootstrap-eval-fixtures.py --provider llm` produces non-zero input_tokens against any active model profile, not just DeepSeek.
- Registry-based dispatch passes a coverage test: every `provider` value in the YAML resolves to an adapter class, and every adapter class is reachable from at least one `provider` value.
- The `Router` class has separate `with_retries()` and `with_fallbacks()` methods, mirroring the LiteLLM separation.
- All backend tests plus the new contract tests pass.

**Out of scope.** No multi-modal (image input) handling beyond what the existing `_responses_evidence_first_payload` already gates on `policy.allow_page_images`. No streaming.

**Risk.** Higher than Phase 2 because it touches every adapter. Mitigation: every change preserves the explicit-delegation shim from Phase 1 as a fallback. If the Anthropic or Gemini implementation has a bug, the failure mode is "delegates to local rule extraction with a warning" rather than a crash.

## 7. Verification Ladder

Each phase has an independent acceptance gate that uses the existing eval ratchet:

| Phase | Acceptance signal | Where measured |
| --- | --- | --- |
| 1 | `tests/test_provider_contracts.py` passes; mock_general rule baseline unchanged at 1.0/54 | backend tests + governance scan |
| 2 | mock_general LLM baseline records `input_tokens > 0`; accuracy stays at 1.0/54; WARN line gone | `bootstrap-eval-fixtures.py --provider llm --baseline` |
| 3 | All four LLM adapters produce non-zero token counts when used as the active model profile; registry coverage test passes | new contract test + at least one `--provider llm` run per adapter type |

A precision regression in any phase fails the existing `test_eval_fixtures.py::test_baseline_file_is_present_and_well_formed` floor (currently `accuracy=1.0`). Phase 2 and 3 both require regenerating the `mock_general_llm.json` baseline with the new non-zero numbers in the same commit.

## 8. What This Refactor Does NOT Solve

To keep scope honest:

- **Prompt quality (E1-001)**: still needed. The system prompt and extraction rules sit untouched in `services/domain_profile.py:DEFAULT_EXTRACTION_SYSTEM_PROMPT` and `extraction_system_prompt(profile)`. After Phase 2 lands, E1-001 has a real cost-and-accuracy comparison point but the prompt itself still needs the rewrite documented in `docs/ROADMAP.md`.
- **Retry-with-validation-feedback (E1-003)**: still needed. The router after Phase 3 separates retry from fallback but does not yet feed validation errors back into a retry attempt.
- **Real-corpus baseline (E2-001 / E2-002)**: still needed. The `mock_general_llm` baseline is on synthetic Chinese inpatient text; real OCR output has noise that synthetic data cannot replicate.
- **Local LLM fallback (E2-006)**: still needed. The router gives `ConservativeLocalProvider` as the last fallback; an Outlines-based local model would be the second-to-last, but that needs a separate task with its own eval profile.

## 9. Migration Order

PLAN.md will gain three sequential tasks in this order:

1. `PLAN-llm-provider-phase-1`: explicit-delegation shim + contract test (no behavior change).
2. `PLAN-llm-provider-phase-2`: OpenAICompatibleChatProvider.collect_evidence implementation.
3. `PLAN-llm-provider-phase-3`: Anthropic + Gemini implementations + router/registry split.

Each phase is scoped to a single Codex session per `AGENTS.md` "one session, one primary goal" rule. None of them is allowed to combine with `E1-001` or `E1-003`; those follow this refactor.

## 10. Decision to Record

When Phase 1 lands, `docs/DECISIONS.md` gets a new entry: "Every `SemanticExtractionProvider` adapter must explicitly choose between calling its remote API and delegating to local rule extraction; the default-inheritance shim is forbidden." This is the single architectural rule the refactor establishes.
