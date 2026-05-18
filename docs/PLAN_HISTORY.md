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
