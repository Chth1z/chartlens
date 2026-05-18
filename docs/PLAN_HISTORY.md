# EYEX PLAN History

This file holds older `PLAN.md` Done entries rotated out per `AGENTS.md` "Documentation Maintenance" rules. Newer entries (the most recent 5) stay in `PLAN.md`. Detailed outcome narratives that pinned an architectural decision are anchored to `docs/DECISIONS.md`; this file records the task scope and what was committed, not the full reasoning.

When adding to this file, append at the bottom in dated, reverse-task-id order (oldest at the top within a section). Do not edit existing entries except to fix factual errors.

## 2026-05 — pre-PLAN_HISTORY rotation

### done PLAN-llm-provider-phase-1 (2026-05-18)

- Made `collect_evidence` and `extract_group` `@abstractmethod` on `SemanticExtractionProvider`. The default body moved to `local_collect_evidence_fallback(document_context, fields)`. Every concrete adapter (`OpenAIResponsesProvider`, `OpenAICompatibleChatProvider`, `AnthropicMessagesProvider`, `GoogleGeminiProvider`, `ConservativeLocalProvider`) declares an explicit override; Phase 2/3 replace the explicit-delegation shims with real upstream calls.
- New `backend/tests/test_provider_contracts.py` (15 tests) pins the rule. AGENTS.md "Architecture Boundaries" gained the explicit-delegation rule.
- Anchor: `docs/DECISIONS.md` 2026-05-18 "Default-inheritance shim for collect_evidence is forbidden".

### done PLAN-llm-baseline-bootstrap (2026-05-18)

- Established `--provider {rule,llm}` on `bootstrap-eval-fixtures.py` so `mock_general.json` (rule) and `mock_general_llm.json` (LLM-assisted) baselines coexist; per-case provider construction; redacted key fingerprint pre-flight; `profile.semantic_provider_kind` tag on disk.
- Surprise discovery: LLM baseline reported `input_tokens=0` because `OpenAICompatibleChatProvider` did not override `collect_evidence`. Tracked as ROADMAP `E1-011`. The bootstrap script now emits a clear WARN line in that case.
- Anchor: opened `docs/LLM_PROVIDER_REFACTOR.md` and `docs/DECISIONS.md` 2026-05-18 LLM-provider entries.

### done E1-005-synonym-widening Close eval-mock-008 recall gaps (2026-05-18)

- Widened schema synonyms (`hypertension_history` += `血压偏高 / 血压增高 / 血压高 / BP高`; `drinking_history` += `嗜酒 / 喝酒 / 酗酒`); rule-only baseline regenerated at 1.0 (54/54).
- Two pinned regression tests on `eval-mock-008` flipped from MISSING to PASS in the same commit.
- New `scripts/check-llm-connectivity.py` and `.ps1` ship with redacted key reporting and a `model_calls` ledger row.

### done PLAN-field-coverage-and-ocr-postprocessing-research (2026-05-18)

- Created `docs/FIELD_COVERAGE.md` (export-template inventory + 7-phase fixture expansion plan) and `docs/OCR_POST_PROCESSING.md` (open-source landscape: pycorrector, ChineseErrorCorrector, CBLUE, PromptCBLUE, SNOMED CT/ICD-10-CN, MinerU, Docling, with license verification).
- ROADMAP gained `E1-009` and `E1-010`. AGENTS.md documentation map updated to reference both files.

### done PLAN-mock-general-challenge-case (2026-05-17)

- Added `eval-mock-008.txt` with non-standard phrasings (`血压偏高`, `嗜酒`); baseline dropped to `accuracy=52/54≈0.9630` with `auto_accept_precision=1.0` (no false positives, only missed positives).
- Two regression tests pinned the `MISSING` behavior so the precision-task lifecycle (fixture/baseline/test triple update) is enforced.

### done PLAN-mock-general-coverage-expansion (2026-05-17)

- Widened `mock_general` from 5 to 7 synthetic fixtures: heart_disease_history positive, stroke_history positive, implicit-negative `既往史：无特殊`, family-history-leak guard.
- Baseline regenerated at `accuracy=1.0` on 48/48 (was 32/32) with no metric regression on the original 5 cases. `field_tags` extended; `test_fixture_count_matches_committed_baseline` raised to 7.

### done E1-005-clause-boundary Positive history span clipped at sentence terminators (2026-05-17)

- Fixed `services/evidence_first.py:_positive_span` to clip left/right windows at `。 ； ; \n` and only consult the LEFT context for negation; right-side negation belongs to a different field.
- Two new regression tests cover `高血压病史10年。否认糖尿病史。` and `吸烟史20年，每日10支。否认饮酒史。`.
- Baseline regenerated at `accuracy=1.0` (32/32); `test_baseline_file_is_present_and_well_formed` floor raised from 0.90625 to 1.0.

### done PLAN-mock-general-baseline (2026-05-17)

- Established the deterministic precision baseline for `mock_general`: 5 synthetic Chinese inpatient fixtures, gold cases in YAML, `scripts/bootstrap-eval-fixtures.py` and `.ps1` with documented exit codes.
- Committed `config/evaluation_profiles/baselines/mock_general.json` (accuracy 0.90625, auto_accept_precision 1.0, evidence_coverage 1.0, unknown_misfill_rate 0.0). Contract test suite in `test_eval_fixtures.py`.

### done E0-008 Field-extraction eval runner (2026-05-17)

- Built `backend/app/services/extraction_eval.py` as the canonical scoring service; FastAPI `/api/evals/*` routes now delegate to it; `scripts/run-extraction-eval.py` and `.ps1` ship with documented exit codes (0 ok, 2 blocked, `--allow-blocked` override).
- Output schema versioned as `extraction-eval-v1`. 9 tests in `test_extraction_eval.py`. Side effect: `routes.py` dropped from 810 to 653 lines, clearing one governance warning.

### done PLAN-write-architecture-doc (2026-05-17)

- Produced `docs/ARCHITECTURE.md` with full pipeline, layering, services map, boundary contracts, data flow detail, and known boundary frictions linked to PLAN tasks.

### done PLAN-write-roadmap (2026-05-17)

- Produced `docs/ROADMAP.md` with E0/E1/E2 phases (8 + 8 + 6 tasks). Every entry carries a stable ID, an eval-profile-anchored acceptance line, and prerequisite IDs.

### done PLAN-write-reference-projects (2026-05-17)

- Produced `docs/REFERENCE_PROJECTS.md` with 15 reference projects (PaddleOCR, MinerU, Docling, olmOCR, Marker, dots.ocr, Unstructured, Instructor, Outlines, LiteLLM, Continue, OpenClaw, Cline, Open WebUI, Dify).
- Every entry verified against the upstream URL with a `License:` line and a `Verified:` date. License-restricted projects (MinerU OSL with additions, Marker GPL-3.0, Open WebUI, Dify) flagged as ideas-only without a `docs/DECISIONS.md` approval.

### done Triage and merge the in-progress ChartLens upgrade into dev (2026-04-30)

- Drove `git status --short` to empty by landing the ~93 in-progress files of the ChartLens upgrade as one explicit integration commit on `dev`.
- Cross-subsystem (backend services, OCR engine modules, frontend, config, scripts, tests) — could not be split without each subset failing tests in isolation. `.gitignore` housekeeping and a perf_counter timing fix landed in the same window.

### done Add dev branch workflow for personal Codex development (2026-04-30)

- `AGENTS.md`, `docs/CODEX_WORKFLOW.md`, and `docs/DECISIONS.md` now define `main`, `dev`, and `codex/<goal>` responsibilities.

### done Delete OCR runtime engine override (2026-04-30)

- Application code no longer reads the old OCR engine override environment variable. OCR engine order comes only from `config/ocr_profiles/*.yaml`.

### done Add personal CI and frontend test entrypoint (2026-04-30)

- Backend tests, frontend tests, and frontend build are now repeatable locally and in CI through `.github/workflows/ci.yml` and `npm test`.

### done PLAN-llm-provider-phase-2 (2026-05-18)

- Implemented `OpenAICompatibleChatProvider.collect_evidence` so DeepSeek / OpenRouter / Moonshot / Qwen / Z.AI / Azure / Custom call `/chat/completions` with `response_format: json_object` and the evidence-first JSON schema. Adapter degrades gracefully to `local_collect_evidence_fallback` on permanent error. Process-local exposure-policy override (`set_runtime_exposure_policy_override`) added for eval bootstrap. Initial `mock_general_llm.json` baseline at `accuracy=0.9259` (50/54) against DeepSeek v4-flash; the 4 failures cluster on `eval-mock-007` implicit-negative (closed by E1-001 prompt rewrite).
- Anchor: `docs/LLM_PROVIDER_REFACTOR.md` Phase 2; ROADMAP E1-011.

### done E1-001 evidence-first prompt rewrite (2026-05-18)

- Rewrote `_evidence_first_system_prompt` to teach the LLM to honor field-level `evidence_policy.implicit_negative_policy` and `allowed_codes`. Closed the 4 known LLM failures on `eval-mock-007` (`既往史：無特殊` interpreted as unknown rather than 0). LLM baseline rose from 0.9259 to 1.0 (50/54 → 54/54); token cost dropped from 72,372/18,757 to 37,792/11,170 (-47.8% input, -40.4% output). `EVIDENCE_FIRST_PROMPT_VERSION` bumped to `eyex-evidence-first-v2`. Backend tests 318 → 326.
- Anchor: `docs/DECISIONS.md` 2026-05-18 "Evidence-first prompt promotes field-level policy above generic rules"; ROADMAP E1-001.


### done PLAN-llm-provider-phase-3 (2026-05-18)

- ROADMAP E1-011 Phase 3. Real `collect_evidence` for `AnthropicMessagesProvider` and `GoogleGeminiProvider`. New `services/llm_provider/registry.py` replaces the if/elif chain in `fallback._provider_for_profile` with a data-driven dispatch table. Every concrete LLM adapter now has a real evidence-first remote call. Privacy boundary preserved. Registry knows 4 adapter kinds with declared `llm_mode` sets. Backend tests 326 → 340.
- Anchor: `docs/LLM_PROVIDER_REFACTOR.md` Phase 3; AGENTS.md "Architecture Boundaries" explicit-delegation rule.

### done PLAN-mock-general-phase-A (2026-05-18)

- Extended `mock_general` to cover `hospital` (string free-text) and `urban_residence` (enum derived from address pre-redaction). Rule-only baseline rose from 1.0/54 to 1.0/72 on 10 fixtures. New `eval-mock-009` (urban) and `eval-mock-010` (rural) plus extended gold on `eval-mock-005` for the unknown path. Privacy boundary pinned by `test_phase_a_address_redaction_holds_in_deidentified_ir`.
- Anchor: `docs/FIELD_COVERAGE.md` Phase A section; ROADMAP E1-010 Phase A.

### done E1-005 rule_pre_accepted shortcut (2026-05-18)

- Wired the `rule_pre_accepted` shortcut in `_extract_document_evidence_first` so phase-1 fields whose group has `semantic_strategy: rule_shortcut` AND `rule_shortcut_extract` returns confidence >= 0.95 bypass the LLM evidence-first chain entirely. Bypassed candidates carry `acceptance_reason="rule_pre_accepted"`, `provenance.source="rule_shortcut"`, `provenance.skipped_llm=True`, `provenance.decision_status="PASS"`. Backend tests 342 → 343. LLM-assisted `mock_general` baseline rose from 0.9722 (70/72) to 0.9861 (71/72).
- Anchor: `docs/DECISIONS.md` 2026-05-18 "rule_pre_accepted shortcut bypasses LLM for high-confidence rule_shortcut groups"; AGENTS.md "Architecture Boundaries".

### done PLAN-llm-evidence-text-substring (E1-001 v3, 2026-05-19)

- Tightened `_evidence_first_system_prompt` and the evidence-first JSON schema so `evidence_text` MUST be a contiguous substring of the cited block's text, and `normalized_code` for free-text/numeric fields MUST be the actual extracted value (never a type-class placeholder like `'text'` or `'integer'`). Bumped `EVIDENCE_FIRST_PROMPT_VERSION` to `eyex-evidence-first-v3`. LLM-assisted `mock_general` baseline rose from 0.9861 (71/72) to 1.0 (72/72) deterministically across 3/3 cache-cleared runs; token cost dropped to 52,674 input / 12,985 output (-28% input, -34% output vs. prior). Backend tests 343 → 344 (new `test_v3_prompt_requires_substring_evidence_text`). Cacheable prefix byte-stability preserved.
- Anchor: ROADMAP E1-001 outcome line; `docs/FIELD_COVERAGE.md` Phase A note.

### done PLAN-mock-general-phase-B (tumor_history, E1-010, 2026-05-20)

- ROADMAP E1-010 Phase B. Extended `mock_general` to cover `tumor_history`. Rule-only baseline rose from 1.0 (72/72) to 1.0 (80/80) on 11 fixtures. New `eval-mock-011` (explicit positive: `恶性肿瘤病史3年` → `tumor_history="1"`) plus extended gold on `eval-mock-007` (implicit-negative: `既往史：无特殊` → `tumor_history="0"`). LLM-assisted baseline also 1.0 (80/80); token cost 26,406 input / 7,946 output. `mock_general.yaml` `field_tags` includes `tumor_history`; `test_eval_fixtures.py` fixture count updated to 11. Coverage: 12/22 schema fields.
- Anchor: `docs/FIELD_COVERAGE.md` Phase B; ROADMAP E1-010 Phase B.
### done PLAN-split-pipeline.py (2026-05-21)

- Split `backend/app/services/pipeline.py` (526 lines) into `pipeline.py` (300, orchestrator), `pipeline_evidence_first.py` (235, evidence-first extraction flow), `pipeline_quality.py` (58, quality summary helpers), and `pipeline_errors.py` (17, error formatting). Pure refactor with no behavior change; all 344 backend tests passed; rule and LLM `mock_general` baselines stayed at 1.0 (80/80); frontend tests and build passed; governance scan cleared the soft-trigger warning for every pipeline file.
- Anchor: AGENTS.md 500-line soft trigger rule.

### done Decide application/ vs services/ flat layout (2026-05-19)

- Resolved the pending architecture decision: formalize `backend/app/services/` subpackages as the canonical backend layout. No `application/` layer. Complex subsystems get subpackage directories (`llm_provider/`, `ocr_engine/`); simpler modules use flat-file-with-prefix pattern (`pipeline_*.py`). Hard size limits from AGENTS.md apply. Unblocked E0-004 (provider split), E0-005 (OCR boundary), and E0-006 (model_providers split).
- Anchor: `docs/DECISIONS.md` 2026-05-19 "Formalize services/ subpackages as the canonical backend layout".

### done PLAN-split-styles-css (2026-05-22)

- Split `frontend/src/styles.css` (3726 lines) into 10 feature-scoped stylesheets under `frontend/src/styles/` (`base.css` 109, `layout.css` 428, `cases.css` 182, `evidence.css` 256, `document.css` 785, `review.css` 429, `settings.css` 592, `providers.css` 269, `diagnostics.css` 253, `components.css` 422). Original `styles.css` reduced to a 10-line barrel using CSS `@import`. `ocrSourceDebug.test.ts` rewired to read the correct split file. All 9 frontend tests pass; build succeeds; governance scan passes with no large-file warnings.
- Anchor: AGENTS.md 500/800-line ceiling rule.

### done E0-004 Split llm_provider adapters and payloads (2026-05-19)

- Reduced `backend/app/services/llm_provider/adapters.py` (760 lines) and `payloads.py` (691 lines) below the AGENTS.md 500-line soft trigger. Replaced `adapters.py` with `adapters/` subpackage (openai_responses 143, openai_compatible 253, anthropic 202, gemini 197, __init__ 28). Extracted evidence-first payload helpers to `payloads_evidence_first.py` (380); kept `payloads.py` (335) for legacy/shared helpers with backward-compat re-exports. Pure refactor; rule baseline 0.9623 (153/159) unchanged; LLM baseline 0.9748 (155/159).
- Anchor: AGENTS.md 500-line soft trigger rule.
### done E0-006 Split model_providers.py (2026-05-19)

- Reduced the 659-line `backend/app/services/model_providers.py` to a focused subpackage with each module ≤ 300 lines: `types.py` (45), `catalog.py` (200), `settings_store.py` (45), `discovery.py` (121), `api.py` (282), `__init__.py` (29). `__init__.py` re-exports the public API plus `httpx`, `explicit_api_keys_for_profile`, and `_fetch_models` for monkey-patch backward compatibility (used by `test_model_profiles.py` and `test_security_hardening.py`); `_provider_state` and `fetch_provider_models` resolve those names via the package namespace at call time so test patches still take effect. Pure refactor with no behavior change; all 344 backend tests passed; rule baseline 0.9623 (153/159) unchanged; frontend tests and build passed; governance scan cleared.
- Anchor: AGENTS.md 500-line soft trigger rule; ROADMAP `E0-006`.

### done PLAN-split-routes (2026-05-19)

- Split the 780-line `backend/app/api/routes.py` into `backend/app/api/routes/` (`__init__.py` 32 re-exports `router` plus the legacy `_pdf_source_render_scale` helper used by `test_api_smoke.py`; `_helpers.py` 229; `health.py` 131; `models.py` 78; `cases.py` 188; `diagnostics.py` 23; `system.py` 197; `evaluations.py` 74). Governance scan now walks the entire `backend/app/api/` tree for `@router.<method>(...)` decorators missing `response_model=`. Two tests that monkey-patched `app.api.routes.{enqueue_case, build_runtime_services}` were rewired to the actual sub-modules. Pure refactor: all 344 backend tests pass; rule baseline 0.9623 (153/159) unchanged; total `app.routes` count 40 unchanged; frontend tests (9) and build pass; governance scan cleared.
- Anchor: AGENTS.md 500-line soft trigger rule.
### done PLAN-split-layout-normalizer (2026-05-19)

- Split `backend/app/services/layout_normalizer.py` (767 lines) into `backend/app/services/layout_normalizer/`: `__init__.py` (4) re-exports `normalize_document_layout` plus `LAYOUT_NORMALIZER_VERSION`; `sections.py` (44) owns `_detect_section`, `_standalone_key_label`, `_is_section_title_like`, `_compact_text`, `_section_id`, `_sections_from_blocks`, `_renumber_blocks`; `block_merging.py` (200) owns same-line and paragraph-wrap merging plus geometry helpers and `_is_screen_chrome` (kept here because `_can_merge_wrapped_paragraph` calls it directly); `classification.py` (118) owns `_classify_blocks`, `_split_patient_header_block_ids`, `_document_region`, `_region_rule_matches`, `_safe_search`, `_is_patient_header`, and the `LAYOUT_NORMALIZER_VERSION` constant; `key_value_derivation.py` (390) owns the full `_derive_*` family plus `_extract_key_values`, `_estimated_span_bbox`, table-cell helpers; `orchestrator.py` (61) owns the public `normalize_document_layout`. Dependency direction is acyclic. Pure refactor: 344 backend tests pass; rule baseline 0.9623 (153/159) byte-identical; frontend tests (9) and build pass; governance scan cleared.
- Anchor: AGENTS.md 500-line soft trigger rule.
