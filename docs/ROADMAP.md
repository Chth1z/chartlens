# EYEX Roadmap

This is the long-horizon view of EYEX precision and structural work. `PLAN.md` holds tasks that are ready to start; `ROADMAP.md` holds the phases and the precision targets behind those tasks.

The roadmap exists to keep technical direction consistent across sessions. Every roadmap task carries:

- a stable ID,
- a measurable acceptance line tied to an eval profile,
- a list of prerequisite IDs,
- the upstream design reference (when one applies, see `docs/REFERENCE_PROJECTS.md`).

A roadmap task that does not yet have an eval profile is not actionable; the prerequisite for it is to extend the matching eval profile first. That keeps the AGENTS.md Precision Tasks rule enforceable: every behavior change lands with before/after numbers.

## Reading the Phases

- **E0 — Governance and structural prerequisites.** Anything that unblocks measurement, splits, or routing. No precision claim required, but `governance` task IDs must still pass the standard quality gates.
- **E1 — Borrow-from-open-source precision improvements.** Each task names the reference project from `docs/REFERENCE_PROJECTS.md` whose pattern is being adopted. Acceptance is measured precision change, not "feature added".
- **E2 — Product-grade precision and throughput.** Larger investments that depend on E0/E1 being stable. Often span multiple sessions and may use feature branches.

Within a phase, lower numbers are not strictly higher priority; prerequisites form the real ordering.

## Eval Profiles That Anchor the Roadmap

| Eval profile | Path | Anchors phases |
| --- | --- | --- |
| `mock_general` (OCR) | `config/ocr_evaluation_profiles/mock_general.yaml` | E0 sanity. CI-safe, lightweight. |
| `synthetic_medical_directml` (OCR) | `config/ocr_evaluation_profiles/synthetic_medical_directml.yaml` | E1 OCR precision on the AMD/DirectML reference workstation. |
| `medical_inpatient_zh` (OCR) | `config/ocr_evaluation_profiles/medical_inpatient_zh.yaml` | E2 OCR with real de-identified corpus (currently blocked, requires fixtures). |
| `mock_general` (extraction) | `config/evaluation_profiles/mock_general.yaml` | E0 / E1 extraction sanity. |
| `medical_inpatient_zh` (extraction) | `config/evaluation_profiles/medical_inpatient_zh.yaml` | E1 / E2 field-level precision and unknown-rate tracking. |

If a roadmap task targets a behavior these profiles do not measure, the first sub-task is to extend the relevant profile.

## Active Baselines

These are the live precision baselines that any E1 task must beat or match. They were measured by `scripts/bootstrap-eval-fixtures.py --profile-id <id> --baseline` and the report is committed to `config/evaluation_profiles/baselines/<profile_id>.json`. The on-disk JSON is the canonical "before" reference; any precision task that improves the metrics must regenerate the baseline as part of the same commit.

| Profile | Provider | accuracy | auto_accept_precision | evidence_coverage | unknown_misfill_rate | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `mock_general` (extraction) | `ConservativeLocalProvider` (rule-only) | 1.0 (54/54) | 1.0 (54/54) | 1.0 (54/54) | 0.0 | 8 synthetic cases. Raised from 0.9630 to 1.0 on 2026-05-18 by the E1-005 synonym widening commit (`hypertension_history` adds `血压偏高/血压增高/血压高/BP高`; `drinking_history` adds `嗜酒/喝酒/酗酒`). The two pinned regression tests were inverted in the same commit (MISSING → PASS). The rule-only baseline now sits at the ceiling of synthetic cases; further precision gains require either an LLM-assisted path (E1-001), tighter `evidence_coverage` definition under the LLM path, or a real-world corpus where new recall gaps emerge naturally (E2-001/E2-002). |

The mock profile uses rule-only extraction so the baseline is deterministic and CI-safe. E1 tasks that introduce LLM calls should record both the rule-only baseline and the LLM-assisted run for the same profile so the cost and the precision contributions can be split.

## E0 — Governance and Structural Prerequisites

### E0-001 — Decide application/ vs services/ flat layout

- Goal: resolve whether `backend/app/` adopts an `application/` orchestration layer or formalizes `services/` subpackages with hard size limits. Record the decision in `docs/DECISIONS.md` before any code reorganization. Already tracked as a `PLAN.md` task; this entry holds the roadmap context.
- Acceptance: `docs/DECISIONS.md` has a dated decision; no code change in this task.
- Prerequisites: none.
- Reference: none. Internal architecture decision.

### E0-002 — Alembic migration baseline

- Goal: replace `Base.metadata.create_all` plus `_ensure_sqlite_columns` with an Alembic baseline that captures all 7 current tables and runs at startup. Tracked in `PLAN.md`.
- Acceptance: fresh DB and existing DB both upgrade through `alembic upgrade head`; the manual shim is deleted; `python -m pytest backend\tests` passes.
- Prerequisites: none, but lands before E2-002.
- Reference: none.

### E0-003 — Processing job recovery on restart

- Goal: on backend startup, scan `processing_runs` for `started/running` rows, mark them `failed` with reason `process_restart_aborted`, and rebound their cases from `extracting/ocr` back to `queued`. Tracked in `PLAN.md`.
- Acceptance: kill the backend mid-processing, restart, verify the case appears as `failed: process_restart_aborted` and reprocess works; unit tests cover the recovery routine.
- Prerequisites: E0-002.
- Reference: none.

### E0-004 — Split llm_provider into protocols / router / credentials

- Goal: reorganize `backend/app/services/llm_provider/` into `protocols/` (one adapter per protocol), `router.py` (fallback chain, key cooldown, error classification, retry policy), `credentials.py` (DPAPI / Keychain / explicit plaintext opt-in). Business pipelines call only the router. Tracked in `PLAN.md`.
- Acceptance: no protocol-specific HTTP code lives in `fallback.py`, `adapters.py`, or `local_extraction.py`; business pipelines do not import a specific protocol adapter directly; `python -m pytest backend\tests\test_provider_fallback.py backend\tests\test_core_business_optimization.py backend\tests\test_security_hardening.py` plus the full backend suite all pass.
- Prerequisites: E0-001 (so the layout decision is settled before splitting).
- Reference: LiteLLM Router shape, Continue config schema, OpenClaw provider catalog. See `docs/REFERENCE_PROJECTS.md`.

### E0-005 — OCR engine vs layout normalizer split

- Goal: move profile-driven same-line merging, paragraph reflow, screen-chrome removal, patient-header detection, and key-value derivation out of `ocr_engine/canonicalize.py` into `services/layout_normalizer.py`. `ocr_engine/` produces raw and single-engine canonical output only. Tracked in `PLAN.md`.
- Acceptance: `canonicalize.py` no longer references screen-chrome patterns or key-value labels; `layout_normalizer.py` owns those rules; OCR eval run on `synthetic_medical_directml` shows no regression on layout/table/reading-order metrics; full backend test suite passes.
- Prerequisites: E0-001.
- Reference: PaddleOCR layered pipeline; Docling reading-order graph; Marker block taxonomy. See `docs/REFERENCE_PROJECTS.md`.

### E0-006 — Split model_providers.py into catalog / store / discovery / api

- Goal: reduce the 659-line `services/model_providers.py` into four focused modules covering YAML loading, persistence and decryption, `fetch_provider_models` plus URL fallback, and the FastAPI request/response shape. Tracked in `PLAN.md`.
- Acceptance: each new module ≤ 300 lines; the original file is a thin re-export shim or removed; full backend and frontend tests pass.
- Prerequisites: E0-004.
- Reference: same as E0-004.

### E0-007 — Split styles.css and EvidencePanel.tsx

- Goal: bring the two biggest frontend files under the AGENTS.md ceiling. `frontend/src/styles.css` (3211 lines) splits by feature folder; `frontend/src/features/cases/EvidencePanel.tsx` already has companion modules but the container needs further reduction. Tracked in `PLAN.md`.
- Acceptance: governance scan reports no large-file warning for either file; `cd frontend; npm test; npm run build` pass; manual smoke walks through cases / settings / diagnostics / review unchanged.
- Prerequisites: none.
- Reference: none. Internal frontend hygiene.

### E0-008 — Field-extraction eval runner (done 2026-05-17)

- Goal: build a CLI runner for `config/evaluation_profiles/*.yaml` analogous to `scripts/run-ocr-eval.py`. The runner loads gold cases, processes them through the pipeline, and reports per-field precision, recall, exact-match, unknown-rate, and token cost. Output schema must be stable so before/after diffs are mechanical.
- Acceptance: `scripts/run-extraction-eval.ps1 -ProfileId mock_general` runs end-to-end and produces a JSON report with the schema documented in the script header; backend tests cover the runner skeleton.
- Prerequisites: none.
- Reference: olmOCR 2 RLVR unit-test harness; Instructor validation-error feedback pattern. See `docs/REFERENCE_PROJECTS.md`. EYEX does not adopt RLVR training; the reference is the verification harness shape.
- Outcome: shipped as `backend/app/services/extraction_eval.py` (the canonical builder), the FastAPI `/api/evals` routes now delegate to that service, and the CLI lives in `scripts/run-extraction-eval.py` plus `scripts/run-extraction-eval.ps1`. Report schema is versioned (`schema_version: "extraction-eval-v1"`) so downstream precision tasks can diff before/after deterministically. The runner does not reprocess cases; gold cases must be uploaded and processed first. Empty profiles or missing cases are reported as `summary.hard_blocker` with non-zero exit unless `--allow-blocked` is passed. Backend tests in `backend/tests/test_extraction_eval.py` cover the schema, scoring, missing-case path, summary aggregation, and CLI exit codes. Side benefit: `routes.py` dropped from 810 to 653 lines, clearing one governance warning.

## E1 — Borrow-from-Open-Source Precision Improvements

### E1-001 — Evidence-first system prompt rewrite

- Goal: rewrite `backend/app/services/llm_provider/payloads.py:_evidence_first_system_prompt` and the medical document profile's `extraction_system_prompt` for higher precision and lower unknown-rate, while preserving DeepSeek prompt-cache prefix stability. The rewrite drops chain-of-thought instructions for clinical extraction (per "LLMs are not Zero-Shot Reasoners for Biomedical Information Extraction" arxiv:2408.12249, which shows standard prompting beats CoT/self-consistency on biomedical IE). It strengthens the evidence-grounding contract: every candidate must reference a verbatim span and a `block_id`, and explicitly forbids name/diagnosis/department-derived inference.
- Acceptance: extraction eval profile run on `medical_inpatient_zh` shows non-decreasing exact-match precision and a non-increasing unknown-rate. Token cost per case does not increase by more than 5% when measured against the recorded baseline. The system-prompt prefix that DeepSeek caches is stable byte-for-byte across requests in the same field group; the eval report records `cache_hit_rate` before and after. On `mock_general`, the LLM-assisted run must close at least 2 of the 3 known recall gaps (positive `hypertension_history` / `smoking_history` cases) without regressing any auto_accepted=true field, and the new baseline is committed alongside the prompt change.
- Prerequisites: E0-008.
- Reference: olmOCR 2 unit-test verifier pattern; biomedical IE arxiv 2408.12249 finding that CoT degrades clinical extraction; DeepSeek context-caching docs (90% cost cut on cached prefixes). See `docs/REFERENCE_PROJECTS.md`.

### E1-002 — DeepSeek prompt-cache prefix discipline

- Goal: restructure all evidence-first and group-extraction payloads so the cacheable prefix (system prompt + rules + schema descriptor) is byte-stable across cases. Move per-case dynamic content (`document_context`, `fields`) to the suffix. Keep `prompt_cache_key` per profile.
- Acceptance: extraction eval run reports `cache_hit_rate` ≥ 90% on a 10-case rerun (second pass over the same cases), measured through DeepSeek's `prompt_cache_hit_tokens` field in `ModelCallRecord`. Token cost per case drops accordingly. No precision change on `medical_inpatient_zh`.
- Prerequisites: E0-008, E1-001.
- Reference: DeepSeek API docs context caching (90% discount on cache hits); LiteLLM cost-tracking pattern. See `docs/REFERENCE_PROJECTS.md`.

### E1-003 — Field-level evidence retry with validation feedback

- Goal: when the validator flags `evidence_span_not_in_block` or `forbidden_inference_used`, the LLM router retries the failing field once with the validation error attached to the user message, instead of dropping the case to manual review. The retry budget per field is 1, never 2 or more. Implementation goes in the new `router.py` from E0-004 plus `services/validation.py`.
- Acceptance: extraction eval run on `medical_inpatient_zh` shows reduction in `manual_review` rate without precision regression on auto-accepted fields. `model_calls.fallback_attempts` is bounded.
- Prerequisites: E0-004, E0-008, E1-001.
- Reference: Instructor validate-and-retry loop. See `docs/REFERENCE_PROJECTS.md`.

### E1-004 — Layout-aware evidence pack windowing

- Goal: improve `services/evidence.py:build_evidence_packs` to use document-region awareness (`patient_header`, `clinical_body`, `signature`, table cells) when picking neighbor blocks. Currently the windowing is FTS-score plus reading-order neighbors. Borrowing pattern: Unstructured element type taxonomy plus Docling reading-order graph traversal. The improvement targets fields where the right answer sits in a same-row table cell or the next paragraph but the FTS score fights against it.
- Acceptance: extraction eval run on `medical_inpatient_zh` shows precision improvement on at least 3 fields whose evidence policy includes `layout_cell` or `layout_key_value`. No regression on fields that already pass.
- Prerequisites: E0-005, E0-008.
- Reference: Unstructured element types; Docling reading-order graph; Marker block taxonomy (ideas only, no source copy). See `docs/REFERENCE_PROJECTS.md`.

### E1-005 — Local rule pre-filter before LLM call (partially done 2026-05-17 + 2026-05-18)

- Goal: tighten `evidence_first.collect_local_evidence` so that high-confidence rule matches (regex hit on patient-header layout key-value with confidence ≥ 0.95) skip the LLM call entirely and record `acceptance_reason=rule_pre_accepted`. Currently the rule layer always defers to LLM adjudication when LLM is available. The change must not affect fields whose `evidence_policy.high_risk=true`.
- Acceptance: extraction eval run shows token cost reduction (target 20% on demographics group) without precision change on auto-accepted fields. Diagnostics ledger surfaces the new `rule_pre_accepted` reason. On `mock_general`, the rule-only baseline (`accuracy=0.90625`, `auto_accept_precision=1.0`) must hold; if positive history rules are widened to recover one or more of the 3 known recall gaps, the new floor is committed and the baseline regenerated.
- Prerequisites: E0-008.
- Reference: PaddleOCR profile-driven shortcut pattern (do not call heavyweight model when light model is sufficient).
- Outcome (partial, 2026-05-17): the recall-gap half of the goal is closed. The fix in `services/evidence_first.py:_positive_span` clips positive-evidence windows to the surrounding clause (sentence terminators `。 ； ; \n`) and only checks the LEFT context for negation; right-side negation belongs to a different field and is now ignored. Two new regression tests in `test_evidence_first_extraction.py` pin the corrected behavior on `高血压病史10年。否认糖尿病史。` and `吸烟史20年，每日10支。否认饮酒史。`. The `mock_general` baseline now scores `accuracy=1.0` (32/32), `auto_accept_precision=1.0`, `evidence_coverage=1.0`, `unknown_misfill_rate=0.0`. The remaining `rule_pre_accepted` shortcut work (skip LLM on high-confidence rule hits, surface the reason in diagnostics) is still open and will land in a follow-up commit.
- Outcome (partial, 2026-05-18): synonym widening for the eval-mock-008 challenge case. Added `血压偏高 / 血压增高 / 血压高 / BP高` to `hypertension_history.synonyms` and `嗜酒 / 喝酒 / 酗酒` to `drinking_history.synonyms`. Both pinned regression tests inverted from MISSING to PASS in the same commit. Baseline regenerated at `accuracy=1.0` (54/54). The `rule_pre_accepted` shortcut work remains the only open piece of E1-005.

### E1-006 — Provider contract test set

- Goal: add `backend/tests/test_provider_contracts.py` covering invalid key (401/403), rate limit (429), timeout, missing `/models` endpoint, and malformed JSON output. Each contract test verifies that the router classifies the error correctly, applies the expected cooldown, and falls through to the next profile in the chain.
- Acceptance: full backend test suite passes; the contract tests fail when `services/llm_provider/fallback.py:_should_try_next_*` is regressed in any direction (verified by intentional regression in a draft branch).
- Prerequisites: E0-004.
- Reference: LiteLLM Router error-classification documentation; OpenClaw fallback chain semantics. See `docs/REFERENCE_PROJECTS.md`.

### E1-007 — Docling as offline OCR eval second source

- Goal: make Docling available as an evaluation-only OCR engine in `.venv-ocr` (not the main backend deps). Wire `scripts/run-ocr-eval.py --engine docling` to produce a parallel layout/table/reading-order report against the same fixture set. Tracked in `PLAN.md`.
- Acceptance: `.\scripts\run-ocr-eval.ps1 -ProfileId mock_general -Engine docling` runs to completion and emits the standard eval report shape. Existing eval runs without `-Engine` are unchanged.
- Prerequisites: none.
- Reference: Docling MIT-licensed package. See `docs/REFERENCE_PROJECTS.md`.

### E1-008 — OCR confidence calibration on DirectML route

- Goal: calibrate the per-block confidence reported by PP-OCRv5 ONNX DirectML so that a confidence band of `quality_thresholds.min_confidence = 0.65` (declared in `windows_radeon_balanced`) corresponds to the actual error rate on `synthetic_medical_directml`. Today the confidence is the raw model output; a calibration table is added to `ocr_engine/calibration.py`.
- Acceptance: OCR eval run on `synthetic_medical_directml` shows that blocks below the calibrated `min_confidence` cover ≥ 90% of CER errors, while the rejection rate on correct blocks stays under 5%. The calibration table version is written into `DocumentIR.metadata.coordinate_transform.merge_policy_version` lineage so cache invalidation is automatic.
- Prerequisites: E0-005.
- Reference: PaddleOCR PP-OCR confidence scoring; Marker block-confidence calibration ideas (no source copy). See `docs/REFERENCE_PROJECTS.md`.

### E1-009 — Eval-only OCR character correction diagnostic

- Goal: run pycorrector's n-gram + pinyin/shape correction layer (Apache-2.0) over the OCR output of the existing OCR eval profiles and produce a "what fraction of characters the corrector would flip, and on which fields" report. Pure diagnostic — does not modify the runtime route. Output decides whether to invest in a real character-correction stage between `ocr_engine` canonical merge and `layout_normalizer`.
- Acceptance: `scripts/run-ocr-eval.ps1 -ProfileId synthetic_medical_directml -CorrectorDiagnostic` (new flag) emits a per-block diff between original OCR text and pycorrector output, plus a count of flips by character and by `DocumentIRBlock.section_label`. Report committed under `config/ocr_evaluation_profiles/diagnostics/<profile>.json`.
- Prerequisites: E1-007 (Docling eval) so the `.venv-ocr` runtime can host another optional NLP package; or independent if pycorrector is added to `.venv-ocr` directly.
- Reference: pycorrector (shibing624) Apache-2.0; "OCR Error Post-Correction with LLMs in Historical Documents" arxiv 2025.resourceful-1.8 cautions on naively wiring SOTA correctors. See `docs/OCR_POST_PROCESSING.md`.

### E1-011 — LLM provider adapters complete the evidence-first contract (multi-phase)

- Goal: every concrete `SemanticExtractionProvider` adapter must implement `collect_evidence` either as a real upstream call or as an explicit delegation to local rule extraction. Today only `OpenAIResponsesProvider` does; DeepSeek / Anthropic / Gemini / OpenRouter / Moonshot / Qwen / Z.AI / Azure / Custom inherit a base-class shim that silently falls back to rule extraction and reports zero input tokens. Surfaced on 2026-05-18 by the `mock_general_llm.json` baseline showing `input_tokens=0`. Detailed analysis and phase plan in `docs/LLM_PROVIDER_REFACTOR.md`.
- Phases (one PLAN task each):
  - **Phase 1 — make the gap a hard error (done 2026-05-18)**: turned `collect_evidence` and `extract_group` into `@abstractmethod`; every adapter now declares an explicit override. `OpenAIResponsesProvider` keeps its real implementation; `OpenAICompatibleChatProvider`, `AnthropicMessagesProvider`, `GoogleGeminiProvider` each return `local_collect_evidence_fallback(...)` with `evidence_collection_method=local_fallback` in `last_usage`. New `tests/test_provider_contracts.py` (15 tests) pins the rule. AGENTS.md and `docs/DECISIONS.md` codify the contract. 318 backend tests pass; mock_general rule baseline (1.0/54) and LLM baseline unchanged on disk.
  - **Phase 2 — OpenAI-compatible chat collect_evidence**: real implementation that calls DeepSeek / OpenRouter / Moonshot / Qwen / Z.AI / Azure / Custom through `client.chat.completions.create` with `response_format: json_object`, JSON schema descriptor in the system prompt prefix for DeepSeek prompt-cache stability, malformed-JSON degradation to local fallback. Mock_general LLM baseline records non-zero `input_tokens` after this phase.
  - **Phase 3 — Anthropic + Gemini + router cleanup**: same shape for the remaining two adapters; extract `Router` class with separate `with_retries()` and `with_fallbacks()` methods (LiteLLM pattern); replace `_provider_for_profile` if/elif with a registry; document and gate the legacy `extract_group` path.
- Acceptance per phase: see `docs/LLM_PROVIDER_REFACTOR.md` section 6.
- Prerequisites: E0-008 (eval runner exists). E1-001 / E1-002 / E1-003 are blocked until at least Phase 2 lands.
- Reference: LiteLLM `Router` 3-layer architecture (`function_with_fallbacks` / `function_with_retries` / unified completion); LangChain `BaseChatModel.with_structured_output`; DeepSeek prompt-cache prefix discipline. See `docs/REFERENCE_PROJECTS.md` and `docs/LLM_PROVIDER_REFACTOR.md` section 5.

### E1-010 — mock_general fixture expansion (multi-phase)

- Goal: expand the synthetic `mock_general` baseline from 8 fixtures (covering 9 of 22 schema fields) to coverage of every export-template column. Phased so that each phase is one PLAN task with its own baseline regeneration. Phase plan documented in `docs/FIELD_COVERAGE.md`.
- Phases (one PLAN task each, executed sequentially):
  - **A** demographics completion (`hospital`, `urban_residence`).
  - **B** history completion (`tumor_history`).
  - **C** imaging facts (`single_multiple`, `aneurysm_location`).
  - **D** score grades (`hh_grade`, `wfns_grade`, `fisher_grade`, `mrs_score`).
  - **E** surgery method (`surgery_method`).
  - **F** timeline durations (`onset_to_admission_time`, `admission_to_surgery_time`).
  - **G** discharge outcome (`in_hospital_death`, `transfer`).
- Acceptance per phase: matching fixtures committed; gold YAML extended; baseline regenerated; `test_eval_fixtures.py` accuracy floor and fixture-count assertion updated; `docs/ROADMAP.md` Active Baselines row reflects the new total. New recall gaps are pinned in `test_evidence_first_extraction.py` rather than silently regressed.
- Prerequisites: E0-008, current `mock_general` baseline (8 cases).
- Reference: `docs/FIELD_COVERAGE.md` for the rationale of each phase ordering.

## E2 — Product-Grade Precision and Throughput

### E2-001 — Real medical OCR corpus and `medical_inpatient_zh` unblock

- Goal: assemble a small de-identified medical OCR fixture set under `config/ocr_evaluation_profiles/fixtures/`. Each case includes `truth_pages`, `truth_blocks`, `truth_tables`. The `medical_inpatient_zh` OCR eval profile is unblocked once at least 5 reviewed cases exist with `directml`, `cuda`, and `rocm_remote` tags as documented in `docs/OCR_UPGRADE.md`.
- Acceptance: `scripts/run-ocr-eval.ps1 -ProfileId medical_inpatient_zh` runs without `-AllowEmptyHardwareProfile` and exits zero. The report establishes the first real-hardware OCR P95 baseline beyond the reference Radeon line in AGENTS.md.
- Prerequisites: none, but landing this gate is a prerequisite for any E1 OCR precision claim that names `medical_inpatient_zh`.
- Reference: PaddleOCR PP-OCRv5 + PP-StructureV3 evaluation methodology.

### E2-002 — Field extraction eval growth and gold expansion

- Goal: grow `config/evaluation_profiles/medical_inpatient_zh.yaml` to cover every high-risk field (those with `evidence_policy.high_risk=true`) with at least 3 gold cases each. The gold cases include conflict, missing, and family-context-trap variants so that adjudication policy is exercised, not only happy paths.
- Acceptance: full extraction eval run produces per-field metrics for every high-risk field; `precision_high_risk_unknown_min` threshold in the profile is met or improved; `unknown_when_evidence_present_max` threshold is enforced.
- Prerequisites: E0-008, E2-001.
- Reference: olmOCR 2 unit-test reward design (every field is one verifiable test).

### E2-003 — Throughput baseline and concurrent processing

- Goal: establish a multi-case throughput baseline. Today `case_workers` is a configured constant. Measure end-to-end P95 for queues of 10/50/100 cases on the reference workstation; document the result in the relevant eval profile artifact directory; pick a target `case_workers` and `llm_workers` per profile.
- Acceptance: a documented throughput baseline exists; processing ledger queries show per-stage contention; the AGENTS.md performance baseline section is updated with the recorded numbers (not assertions, evidence).
- Prerequisites: E0-002, E0-003.
- Reference: none.

### E2-004 — Decide LiteLLM sidecar adoption

- Goal: revisit whether to adopt LiteLLM as a sidecar (with pinned image digest, isolated credentials, dedicated allowlist) for unified provider routing. Decision goes in `docs/DECISIONS.md` and references the upstream post-incident remediation note from the 2026-03 PyPI compromise. Outcome can be "yes as sidecar", "no, hand-roll", or "deferred".
- Acceptance: a dated `docs/DECISIONS.md` entry. If the outcome is "yes", a follow-up E2 task lands the sidecar wiring with cooldown and contract tests intact.
- Prerequisites: E0-004, E1-006.
- Reference: LiteLLM Router; LiteLLM 2026-03 PyPI compromise issue. See `docs/REFERENCE_PROJECTS.md`.

### E2-005 — OpenAPI-driven frontend types

- Goal: replace the hand-written `frontend/src/shared/api/schemas.ts` zod definitions with a single source of truth derived from the FastAPI OpenAPI document. Backend response models stay the canonical schema; a generation step produces zod (or valibot) types. Removes the manual sync burden when `response_model` changes. Builds on the PLAN task "Replace hand-written API validators with zod schemas" which is already done; this task extends it to generation.
- Acceptance: schema generation runs in `npm run build` or as a pre-commit step; existing 9 frontend tests pass; one backend contract change forces exactly one regeneration step on the frontend, not a manual edit.
- Prerequisites: E0-001 (so the layout decision is settled).
- Reference: Continue's typed config; standard `openapi-zod-client` or `orval` patterns (no source copy).

### E2-006 — Local LLM fallback option

- Goal: add a constrained-decoding local LLM fallback for cases where the remote LLM is unavailable and rule-only extraction leaves too many fields unknown. Implementation uses Outlines plus a small instruction-tuned model in `.venv-ocr`. Activation is opt-in through `model_profile=local_constrained`. Privacy boundary stays the same: the local fallback only consumes the de-identified DocumentIR.
- Acceptance: extraction eval run with the remote provider disabled shows a measured improvement on auto-accepted high-risk fields versus the existing `ConservativeLocalProvider`; latency stays inside an explicitly accepted budget recorded in the profile.
- Prerequisites: E0-004, E2-002.
- Reference: Outlines token-level constrained decoding; Instructor validation feedback. See `docs/REFERENCE_PROJECTS.md`.

## Discharge Conditions

A roadmap task is discharged when:

- it has a corresponding `PLAN.md` task or a single completed commit on `dev`,
- the eval profile run is recorded with the commit (per AGENTS.md Precision Tasks),
- this file's task entry is updated to mark `done`, or removed if the task no longer makes sense.

A roadmap task that becomes irrelevant is removed with a `docs/DECISIONS.md` entry stating why; do not leave dead tasks in this file.
