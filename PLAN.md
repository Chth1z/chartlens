# EYEX Personal Task Board

This file is the lightweight project board for personal Codex-assisted development. Keep tasks small enough for one focused session and concrete enough to verify.

## Operating Rules

- One active task per Codex session.
- Every task must define: goal, out of scope, acceptance commands, risk, and status.
- Large work is split into 1-3 day increments. Avoid big-bang rewrites.
- Technical debt must have a trigger and a done condition. Do not write vague "optimize later" items.
- High-impact decisions go to `docs/DECISIONS.md`.

## Task Template

```markdown
### <status> <short task title>

- Goal:
- Out of scope:
- Acceptance commands:
- Risk:
- Trigger:
- Done condition:
```

## Active / Next

### todo PLAN-llm-evidence-text-substring (E1-001 v3)

- Goal: Tighten `_evidence_first_system_prompt` and the evidence-first JSON schema so that the LLM's `evidence_text` field MUST be a contiguous substring of the cited block's text. Closes the two LLM gaps surfaced by Phase A: `eval-mock-009 / hospital` returns `'text'` (LLM echoing the schema's `allowed_codes=[text, unknown]` placeholder) and `eval-mock-010 / diabetes_history` paraphrases `否认糖尿病` from the verbatim `否认高血压病、糖尿病、冠心病等病史`. Bump `EVIDENCE_FIRST_PROMPT_VERSION` to `v3` so cached results from v2 are auto-invalidated.
- Out of scope: No change to `allowed_codes` schema literals. No retry loop (E1-003 territory). No prompt-cache prefix migration (E1-002 territory) — keep the cacheable prefix byte-stable so DeepSeek prompt-cache still hits.
- Acceptance commands: `Remove-Item var\storage\llm_cache -Recurse -Force; python scripts\bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --unsafe-eval-allow-remote-context --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Risk: Medium. A prompt rewrite could regress already-passing fields. Mitigations: Phase A privacy-redaction tests still run; the byte-stability test in `test_evidence_first_prompt.py` catches per-case leaks; the rule-only baseline 1.0/72 is the floor.
- Trigger: ROADMAP E1-001 follow-up surfaced 2026-05-18; mock_general LLM baseline currently 0.9861 (71/72); the single failure pattern is the same family of placeholder-echo bug for both `hospital` and the `diabetes_history` paraphrase.
- Done condition: prompt v3 explicitly requires `evidence_text` contiguous-substring of `text`; for string-type fields (`hospital`, free-text), prompt teaches that `normalized_code` must be the actual extracted value, not the type-class placeholder; new regression test `test_v3_prompt_requires_substring_evidence_text` pins the rule; LLM baseline reaches 1.0 (72/72) on at least 3 of 5 cache-cleared runs (i.e. variance shifts from "deterministic single failure" to "occasional variance"); `EVIDENCE_FIRST_PROMPT_VERSION = "eyex-evidence-first-v3"`; ROADMAP E1-001 outcome line dated 2026-05-19 (or whenever this lands) records the new baseline; DECISIONS.md gains a v3 entry only if a structural prompt-shape change beyond text-tightening lands.

### todo PLAN-mock-general-phase-B (tumor_history)

- Goal: ROADMAP E1-010 Phase B. Extend `mock_general` to cover `tumor_history`. Reuse `eval-mock-007` (already has `既往史：无特殊` implicit-negative pattern) by adding `tumor_history: "0"` to its gold; add one new fixture (`eval-mock-011`) with explicit `恶性肿瘤史` for the positive path; optionally add `tumor_history: "0"` to `eval-mock-001` / `eval-mock-002` for explicit-negative coverage if their `否认...病史` clauses include it.
- Out of scope: No schema synonym change unless a recall gap appears. No phase C-G work. No new field beyond `tumor_history`.
- Acceptance commands: `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline`; `Remove-Item var\storage\llm_cache -Recurse -Force; python scripts\bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --unsafe-eval-allow-remote-context --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Risk: Low. Same rule shape as the existing diabetes / heart-disease history fields; the schema's `implicit_negative_policy: section_complete_only` already covers the negative path.
- Trigger: ROADMAP E1-010 Phase A is done (2026-05-18); phase ordering in `docs/FIELD_COVERAGE.md`.
- Done condition: at least one fixture asserts `tumor_history="1"` (positive path); at least one fixture asserts `tumor_history="0"` (explicit-negative or section-complete-implicit-negative); `mock_general.yaml` `field_tags` includes `tumor_history`; rule-only baseline regenerated; LLM-assisted baseline regenerated; `test_eval_fixtures.py::test_fixture_count_matches_committed_baseline` updated; `docs/ROADMAP.md` Active Baselines row updated; `docs/FIELD_COVERAGE.md` Phase B status moved from todo to done.

### todo PLAN-split-pipeline.py

- Goal: Split `backend/app/services/pipeline.py` (currently 526 lines, over the AGENTS.md 500-line soft trigger) along behavior boundaries. Suggested split: keep `pipeline.py` as the orchestrator (`process_case` + group dispatch); extract `pipeline_evidence_first.py` (the `_extract_document_evidence_first` flow including the 2026-05-18 `rule_pre_accepted` partition), `pipeline_quality.py` (page-quality summary, OCR-quality lookup), and `pipeline_errors.py` (formatting helpers like `_format_provider_failure`).
- Out of scope: No business behavior change. No new field, no schema change. The export gate contract (`provenance.decision_status="PASS"`) and the `rule_pre_accepted` shortcut behavior must be preserved exactly.
- Acceptance commands: `python -m pytest backend\tests` (343 must still pass); `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`. Both rule and LLM `mock_general` baselines must reproduce exactly (`accuracy=1.0` rule, `accuracy=0.9861` LLM on the chosen run).
- Risk: Medium. The pipeline composes several long-lived contracts (trace recording, provider call boundaries, the export gate). Module boundary changes can introduce circular imports or accidentally drop a `model_copy(update=...)` call. Mitigation: every behavior path covered by the existing 343 tests; baseline reproduction is the hard contract.
- Trigger: AGENTS.md "the next task touching this file must include a split" — `pipeline.py` crossed 500 lines on 2026-05-18 commit `be04ad6`. Any further pipeline-touching feature work must do the split first.
- Done condition: each new file ≤ 500 lines; `pipeline.py` itself ≤ 500 lines; governance scan reports no large-file warning for any of the new files; backend and frontend tests both pass; both `mock_general` baselines reproduce identically.

### todo PLAN-split-styles-css

- Goal: Split `frontend/src/styles.css` (currently 3211 lines) into feature-scoped stylesheets that match the `frontend/src/features/` layout. Aim for ≤ 800 lines per file. Suggested split: a base/reset module, an evidence panel module, a settings module, a diagnostics module, and a review module. Use CSS imports or component-level imports, not a runtime concatenation step.
- Out of scope: No visual change. No design-system or Tailwind migration in this task.
- Acceptance commands: `cd frontend; npm test; npm run build`. Manual smoke: open the app, walk through cases, settings, diagnostics, and review and confirm visuals are unchanged.
- Risk: Selectors that depend on rule order can break when split across files; verify by running the build and a smoke pass.
- Trigger: AGENTS.md soft trigger at 500 lines plus hard governance warning at 800 lines; the file is currently the largest in the repository.
- Done condition: Each new stylesheet ≤ 800 lines, the governance scan reports no large-file warning for `frontend/src/styles.css`, and the existing 9 frontend tests pass.

### todo Decide application/ vs services/ flat layout

- Goal: Resolve the dev-vs-main divergence. Either restore the `backend/app/application/` layer that exists on `main`, or formalize `backend/app/services/` subpackages with hard size limits in AGENTS.md. The chosen direction is recorded in `docs/DECISIONS.md` before any code in `services/` or `application/` is reorganized.
- Out of scope: No business behavior change. No new feature in this task.
- Acceptance commands: `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Risk: Without a recorded decision, future split tasks (provider, pipeline, OCR boundary) keep blocked by an absent layer; pipeline.py keeps mixing orchestration, error formatting, worker pool, quality summary.
- Trigger: Future split tasks (provider, pipeline, OCR boundary) keep waiting on this layout decision; pipeline.py crossed the 500-line soft trigger on 2026-05-18 and must split as part of its next-touching task.
- Done condition: `docs/DECISIONS.md` has a dated decision; `pipeline.py` either no longer mixes orchestration with formatting/worker/quality, or has a follow-up task in PLAN to split it under the chosen layout.

### todo Add database migration baseline before schema expansion

- Goal: Replace the manual `Base.metadata.create_all(...)` plus ad hoc `_ensure_sqlite_columns` `ALTER TABLE` path with an Alembic migration baseline. Startup runs `alembic upgrade head`. Fresh DB and existing DB go through the same path.
- Out of scope: No move to Postgres. No schema additions in this task.
- Acceptance commands: `python -m pytest backend\tests`; manually verify a fresh `var/storage/eyex.sqlite3` is created on first run and an existing one upgrades without manual SQL.
- Risk: Manual `create_all` and ad hoc `ALTER` will become unsafe as review, eval, and job history grow.
- Trigger: Before adding the next persistent table or non-null column.
- Done condition: `alembic` is in `requirements.txt`, baseline migration captures all 7 current tables, startup runs migrations, and the manual `_ensure_sqlite_columns` shim is deleted.

### todo Move persistent processing jobs out of process memory

- Goal: Replace the `ThreadPoolExecutor + BoundedSemaphore` in-memory queue assumption. On startup, scan `processing_runs` for `started/running` rows, mark them `failed` with reason `process_restart_aborted`, and rebound their cases from `extracting/ocr` back to `queued` so `enqueue_case` can pick them up. Failed runs are never silently retried; the operator sees a diagnostic reason.
- Out of scope: No external queue (Redis, RQ, Celery) for v1. No retry policy beyond explicit re-enqueue.
- Acceptance commands: `python -m pytest backend\tests`; manual: kill the backend mid-processing, restart, verify the case appears as `failed: process_restart_aborted` and reprocess works.
- Risk: Uploads in flight at restart silently disappear from the queue and stay stuck in `extracting/ocr` forever.
- Trigger: After Alembic migration baseline lands (depends on durable schema changes).
- Done condition: A startup recovery routine exists, has unit tests, and is documented in `docs/DECISIONS.md` if the recovery contract changes.

### todo Split EvidencePanel.tsx into transcript / source / overlay

- Goal: Reduce 2017-line `frontend/src/features/cases/EvidencePanel.tsx` to ≤ 500 lines per file by splitting into `EvidencePanel.tsx` (container + view-mode switch), `TranscriptView.tsx`, `SourceImageView.tsx`, `useEvidenceSelection.ts`, and `evidenceGrouping.ts` (pure functions).
- Out of scope: No visual change. No new evidence rendering feature.
- Acceptance commands: `cd frontend; npm test; npm run build`. Manual smoke: open a processed case, verify transcript view and source view both still highlight the active field result and scroll the active block into view.
- Risk: Selection state and image-retry state are tangled; missing dependency in extracted hooks can break highlight/scroll behavior.
- Trigger: Already triggered by the 500-line ceiling; no other prerequisite.
- Done condition: Each new file ≤ 500 lines, existing 9 frontend tests pass, `caseId`-driven image cache invalidation still works.

### todo Replace hand-written API validators with zod or valibot

- Goal: Cut `frontend/src/shared/api/client.ts` (531 lines) plus the matching contract validators in `shared/types/api.ts` from ~1162 lines combined to ~600 lines by introducing a single runtime schema definition. `client.ts` only assembles fetch and translates errors; types come from `z.infer` (or valibot equivalent).
- Out of scope: No new endpoint. No backend contract change. The current `ApiError(502)` invariant on malformed 2xx responses must be preserved.
- Acceptance commands: `cd frontend; npm test; npm run build`.
- Risk: Wrong schema migration silently widens accepted shapes. Bundle size may grow if zod is chosen over valibot.
- Trigger: Before the next backend contract change that adds or removes endpoint fields.
- Done condition: One canonical `frontend/src/shared/api/schemas.ts` covers all endpoints; existing validator helpers are removed; existing 9 tests pass.

### todo Split provider responsibilities under llm_provider/

- Goal: Reorganize `backend/app/services/llm_provider/` into three explicit layers: `protocols/` (one adapter per protocol: OpenAI Responses, OpenAI Chat-compatible, Anthropic Messages, Gemini), `router.py` (fallback chain, key cooldown, error classification, retry policy), and `credentials.py` (DPAPI / Keychain / explicit plaintext opt-in). `services/extraction/` calls only the router.
- Out of scope: No prompt or model semantics change. No new provider in this task.
- Acceptance commands: `python -m pytest backend\tests\test_provider_fallback.py backend\tests\test_core_business_optimization.py backend\tests\test_security_hardening.py`; full `python -m pytest backend\tests` before merge.
- Risk: Provider fallback and cache behavior can regress silently. Key cooldown timing is hard to test deterministically.
- Trigger: After application/services layout decision lands; or any new provider, fallback, prompt, or cache change.
- Done condition: No protocol-specific HTTP code lives in `fallback.py`, `adapters.py`, or `local_extraction.py`; business pipelines do not `import` a specific protocol adapter directly (enforced by governance scan).

### todo Split model_providers.py into catalog / store / discovery / api

- Goal: Reduce the 659-line `backend/app/services/model_providers.py` to four focused modules: `model_providers/catalog.py` (YAML loader), `model_providers/settings_store.py` (persistence + decryption), `model_providers/discovery.py` (`fetch_provider_models` + URL fallback), and `model_providers/api.py` (FastAPI request/response shape).
- Out of scope: No change to provider catalog YAML schema. No new provider added.
- Acceptance commands: `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`.
- Risk: Provider settings schema is mirrored in frontend types; module boundary changes must not break import paths used by tests.
- Trigger: After the llm_provider/ split, since both move toward the same router/credentials boundary.
- Done condition: Each new module ≤ 300 lines, the `services/model_providers.py` file no longer exists or is a thin re-export shim.

### todo Clarify ocr_engine vs layout_normalizer boundary

- Goal: Move all profile-driven same-line merging, paragraph reflow, screen-chrome removal, patient-header detection, and key-value derivation out of `ocr_engine/canonicalize.py` and into `services/layout_normalizer.py`. `ocr_engine/` only produces raw blocks plus single-engine canonical merging.
- Out of scope: No change to the `ocr-canonical-layout-v3` merge policy version contract. No new OCR engine.
- Acceptance commands: `python -m pytest backend\tests\test_layout_normalization.py backend\tests\test_ocr_engine_modules.py backend\tests\test_ocr_regression.py`; full `python -m pytest backend\tests` before merge; one OCR eval profile run.
- Risk: Two layers currently both write to `metadata.layout_normalization` / `canonical_blocks_version`; moving rules between them can produce visible OCR text drift if not eval-checked.
- Trigger: After application/services layout decision.
- Done condition: `canonicalize.py` no longer references screen-chrome patterns or key-value labels; `layout_normalizer.py` owns those rules; an OCR eval run shows no regression on the existing fixture set.

### todo Prune dead schema fields in domain/models.py

- Goal: Identify and remove fields on `ExtractionCandidate`, `EvidencePack`, `EvidenceCandidate`, and `DocumentIRBlock` that have no read site in `services/` or `frontend/`. Initial suspects: duplicate `evidence_packs` vs `evidence_candidates`, `candidate_id`, `candidate_group_id`, `canonical_source_ids`, `layout_region_id`, `line_group_id` when no consumer references them.
- Out of scope: No business behavior change. Fields used only by tests still count as "used" if the tests are not removed.
- Acceptance commands: `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`.
- Risk: A field that looks dead may be consumed via dynamic JSON shape (e.g., `model_dump()` then frontend reads). Must grep both backend and frontend for every field name before deletion.
- Trigger: Quarterly schema-cleanup checkpoint declared in AGENTS.md.
- Done condition: Every remaining Pydantic field has at least one explicit read site outside `domain/models.py`; deletion lands with passing tests.

### todo Add Docling as offline OCR eval second source (ROADMAP E1-007)

- Goal: Make Docling available as an evaluation-only OCR engine. Add it to `.venv-ocr` (not main backend deps), wire `scripts/run-ocr-eval.py` to accept `--engine docling`, and produce a parallel layout/table/reading-order report against the same fixture set.
- Out of scope: No change to the runtime OCR route. No CUDA/ROCm requirement.
- Acceptance commands: `.\scripts\run-ocr-eval.ps1 -ProfileId mock_general -Engine docling` runs to completion. Existing eval runs still work without `-Engine`.
- Risk: Docling pulls heavy transitive deps; must stay in `.venv-ocr` so backend deps do not balloon.
- Trigger: Tracked in `docs/ROADMAP.md` as E1-007. Pull forward when an OCR layout/table regression appears that PP-StructureV3 alone cannot diagnose.
- Done condition: Repository can produce a Docling layout/table report on existing fixtures; `docs/OCR_UPGRADE.md` documents that Docling is eval-only.

### todo Convert frontend tests to Vitest when assertions grow

- Goal: Move current script-based frontend tests in `frontend/scripts/run-tests.mjs` to Vitest the next time a test legitimately needs DOM assertions, async lifecycle, fake timers, or mocking.
- Out of scope: No browser E2E suite in this task. No test rewrite if the current minimal runner still covers the assertion needed.
- Acceptance commands: `cd frontend; npm test; npm run build`.
- Risk: The current tiny runner is intentionally minimal; switching too early adds toolchain weight without benefit.
- Trigger: Next frontend test that needs `vi.useFakeTimers`, DOM queries, async test lifecycle, or module mocking.
- Done condition: `npm test` runs Vitest, all existing tests pass, and the previous runner files are removed.

## Done

### done E1-005 rule_pre_accepted shortcut

- Goal: ROADMAP E1-005. Wire the long-open `rule_pre_accepted` shortcut in `_extract_document_evidence_first` so that phase-1 fields whose group has `semantic_strategy: rule_shortcut` AND whose `rule_shortcut_extract` returns a candidate at confidence ≥ 0.95 bypass the LLM evidence-first chain entirely. Tag the bypassed candidates with `acceptance_reason="rule_pre_accepted"` plus `provenance.source="rule_shortcut"` / `provenance.skipped_llm=True`. Close the `eval-mock-003 / age` LLM gap surfaced by E1-010 Phase A (LLM was returning `normalized_code='integer'` echoing the schema's `allowed_codes` placeholder; the rule path `_extract_age` returns `'72'` correctly at confidence 0.96).
- Outcome: implemented as a partition step at the top of `_extract_document_evidence_first`. `rule_shortcut_candidates: dict[str, ExtractionCandidate]` collects the pre-accepted hits via `rule_candidate.model_copy(update=...)`; `llm_fields: list[FieldDefinition]` is what gets passed to `evidence_provider.collect_evidence`, `adjudicate_fields`, `verify_against_document`, and `decisions_to_extraction_candidates`. Trace `field_count` mirrors the reduced LLM count. After `candidates_by_key` is built from the LLM stages, `rule_shortcut_candidates` is merged in (rule wins) so a stale LLM result cannot overwrite the bypass. The export gate is preserved by also stamping `provenance.decision_status="PASS"` on the rule candidate (otherwise the workbook gate `validation_state=accepted AND provenance.decision_status==PASS` would reject rule-pre-accepted gender/age and regress `test_table_cell_demographics_flow_from_layout_to_export`). New regression test `test_rule_shortcut_high_confidence_skips_llm_collect_evidence` builds an asserting fake provider that raises `RuntimeError` if `age` ever appears in `collect_evidence`'s `fields` argument; backend tests rise 342 → 343. LLM-assisted `mock_general` baseline rises from 0.9722 (70/72) to 0.9861 (71/72) on the chosen baseline run; across 5 cache-cleared runs the spread is 70-72/72 with `age` deterministically PASS in every run (`eval-mock-003 / age` is now 100% reliable). The single residual failure on the chosen baseline is `eval-mock-009 / hospital` where DeepSeek v4-flash returned `text` (echoing the schema's `allowed_codes=[text, unknown]` placeholder); this is the same family of LLM failures as the original age regression but on a field whose rule confidence is 0.88 and so does not qualify for the shortcut. Token cost on the chosen run is 73,037 input / 19,743 output; per-call demographics input is reduced because `gender` / `age` / `hospital` no longer round-trip through the LLM when rule confidence ≥ 0.95.
- Acceptance commands: `python -m pytest backend\tests\test_evidence_first_extraction.py -x --tb=short` (10 passed, includes the new test); `python -m pytest backend\tests --tb=short -q` (343 passed); `python scripts\bootstrap-eval-fixtures.py --profile-id mock_general --baseline` (rule baseline 1.0 (72/72) unchanged); `Remove-Item var\storage\llm_cache -Recurse -Force; python scripts\bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --unsafe-eval-allow-remote-context --baseline` (LLM baseline 0.9861 (71/72), `eval-mock-003 / age` flips to PASS); `cd frontend; npm test; npm run build` (9 passed; build OK); `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1` (only pre-existing styles.css warning).
- Done condition: `_extract_document_evidence_first` partitions phase-1 fields into rule-pre-accepted vs LLM groups; rule-pre-accepted candidates carry `acceptance_reason="rule_pre_accepted"`, `provenance.source="rule_shortcut"`, `provenance.skipped_llm=True`, `provenance.decision_status="PASS"`; the asserting fake provider regression test exists in `test_evidence_first_extraction.py`; rule baseline unchanged at 1.0 (72/72); LLM baseline ≥ 0.9861 (71/72) with `eval-mock-003 / age` deterministically passing; `docs/ROADMAP.md` E1-005 marked done with the outcome line dated 2026-05-18; ROADMAP Active Baselines row updated to 0.9861 with the new token totals; `docs/DECISIONS.md` 2026-05-18 entry "rule_pre_accepted shortcut bypasses LLM" added above the existing same-date entries; `config/extraction_schemas/medical_inpatient_zh.yaml` and `services/rules.py` untouched (the shortcut reads but does not change rule contracts).



### done PLAN-mock-general-phase-A

- Goal: ROADMAP E1-010 Phase A. Extend the `mock_general` baseline to cover the two demographics fields outside the 8-case set: `hospital` (string free-text) and `urban_residence` (enum derived from address pre-redaction). Add one fixture with an urban address + hospital label, one fixture with a rural address + hospital label, and anchor the unknown path by extending an existing fixture's gold.
- Outcome: rule-only baseline rises from 1.0/54 to 1.0/72 (10 cases × variable field counts). New fixtures `eval-mock-009` (`家庭住址：南京市鼓楼区五一路`, hospital `海安市第三人民医院`, gold `urban_residence=2`) and `eval-mock-010` (`家庭住址：海安县曲塘镇五星村3组`, hospital `海安县中医院`, gold `urban_residence=1`); `eval-mock-005` gold extended with `hospital=unknown` and `urban_residence=unknown` to anchor the unknown path. The hospital rule (`_extract_hospital`) matches both names verbatim; the `urban_residence` `pre_redaction_derivations` rule fires correctly on both city and rural addresses and emits the safe `是否城市判定` derivation block. Privacy boundary verified by new parametrized test `test_phase_a_address_redaction_holds_in_deidentified_ir`: original `家庭住址` lines collapse to `[REDACTED]` in the de-identified DocumentIR; only the safe derivation block carries forward. The LLM-assisted baseline drops from 1.0 (54/54) to 0.9722 (70/72) because the wider fixture set surfaces two unrelated LLM gaps (`eval-mock-003 / age` returns `normalized_code='integer'` because the LLM echoes the schema's `allowed_codes=[integer, unknown]` placeholder literal; `eval-mock-010 / diabetes_history` fails the `evidence_span` validator because the LLM paraphrases `否认糖尿病` from the verbatim `否认高血压病、糖尿病、冠心病等病史`). Both are honest LLM gaps, not Phase A regressions; both become next-up targets for the open `rule_pre_accepted` shortcut (E1-005) and a v3 prompt rewrite. Token cost rose from 37,792 input / 11,170 output to 51,037 / 15,049 (-2 cases, +35% per total), per-case cost roughly comparable.
- Acceptance commands: `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline` (rule baseline); `Remove-Item var\storage\llm_cache -Recurse -Force; python scripts\bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --unsafe-eval-allow-remote-context --baseline` (LLM baseline); `python -m pytest backend\tests` (342 passed); `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: 10 fixtures committed (8 prior + 2 new); `eval-mock-005` gold extended; `mock_general.yaml` `field_tags` lists `hospital` and `urban_residence`; both rule-only baseline and LLM-assisted baseline regenerated; `test_eval_fixtures.py::test_fixture_count_matches_committed_baseline` raised to 10; new parametrized privacy test `test_phase_a_address_redaction_holds_in_deidentified_ir` covers both new fixtures; `docs/ROADMAP.md` Active Baselines row updated to 1.0/72 (rule) and 0.9722/72 (LLM); `docs/FIELD_COVERAGE.md` Phase A status updated.

### done PLAN-llm-provider-phase-3

- Goal: ROADMAP E1-011 Phase 3. Real `collect_evidence` for `AnthropicMessagesProvider` (system + messages with the JSON schema descriptor in the cacheable system field) and `GoogleGeminiProvider` (systemInstruction + responseMimeType=application/json + responseSchema). New `services/llm_provider/registry.py` replaces the if/elif chain in `fallback._provider_for_profile` with a data-driven dispatch table that pairs each provider literal with its allowed `llm_mode` set. Contract tests pin payload shape, byte stability, real-implementation references, and registry coverage.
- Outcome: every concrete LLM adapter now has a real evidence-first remote call. Anthropic adapter posts to `/v1/messages` with the byte-stable system prompt + JSON schema descriptor and graceful local fallback on auth/timeout/rate-limit/malformed-JSON. Gemini adapter posts to `/v1beta/models/<model>:generateContent` with `responseSchema` translated from the JSON Schema fragment via `_gemini_response_schema` (drops `additionalProperties`, folds `type: ['x', 'null']` into `nullable: true`, uppercases types to OpenAPI 3.0 dialect). Privacy boundary preserved: both adapters honor `safe_evidence_only` policy and degrade to `local_collect_evidence_fallback` with `remote_skipped_reason=remote_full_context_disabled` when the schema disallows full context. Registry knows 4 adapter kinds (`openai_responses`, `openai_compatible`, `anthropic_messages`, `google_gemini`); each declares its allowed `llm_mode` set. Backend tests 326 → 340 (14 new in `test_provider_phase_3.py`). Frontend 9 / build OK / governance scan clean. The `Router.with_retries()` / `Router.with_fallbacks()` LiteLLM-style class extraction is intentionally deferred: `ModelFallbackProvider` already separates fallback iteration from per-adapter retry/cooldown, and splitting them would be churn without behavior change. Same call decision for the legacy `extract_group` path: it stays because the medical schema's `aneurysm_group`, `surgery_group`, and `score_group` use `semantic_strategy: llm_facts_then_compute` and demographics groups use `rule_shortcut`, so removing `extract_group` would require a coordinated schema rewrite that is out of scope.
- Acceptance commands: `python -m pytest backend\tests` (340 passed); `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`. mock_general LLM baseline unchanged (1.0/54 via DeepSeek v4-flash; this batch did not change DeepSeek behavior, only added Anthropic/Gemini real calls).
- Done condition: `AnthropicMessagesProvider.collect_evidence` and `GoogleGeminiProvider.collect_evidence` are real implementations referenced by `_anthropic_evidence_first_payload` and `_gemini_evidence_first_payload`; `services/llm_provider/registry.py` is the single dispatch source and `fallback._provider_for_profile` is a thin delegating shim; new `test_provider_phase_3.py` (14 tests) pins payload byte-stability, real-implementation references, registry coverage, llm_mode gating, and the privacy boundary fallback path; ROADMAP E1-011 marked done.

### done E1-001 evidence-first prompt rewrite

- Goal: Rewrite `_evidence_first_system_prompt` so it teaches the LLM to honor field-level `evidence_policy.implicit_negative_policy` and `allowed_codes` instead of falling back to a generic "missing means unknown" default. The medical schema declares `section_complete_only` for chronic-disease and lifestyle fields, but the previous prompt's generic safe-unknown rule overrode that policy and produced 4 known LLM failures on `eval-mock-007` (`既往史：无特殊` interpreted as unknown rather than 0).
- Outcome: mock_general LLM baseline rises from 0.9259 to **1.0** (50/54 → 54/54) AND token cost drops from 72372/18757 to **37792/11170** (-47.8% input, -40.4% output). All 4 eval-mock-007 fields (`hypertension_history`, `diabetes_history`, `heart_disease_history`, `stroke_history`) now correctly return `0` based on `既往史：无特殊` matching the section-complete pattern. The cacheable prefix is byte-stable; `EVIDENCE_FIRST_PROMPT_VERSION` bumped from `eyex-evidence-first-v1` to `eyex-evidence-first-v2` so cached results from the old prompt are automatically invalidated.
- Acceptance commands: `Remove-Item var\storage\llm_cache -Recurse -Force; python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --unsafe-eval-allow-remote-context --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: rewritten prompt promotes field-level policy above generic rules (`字段证据政策优先` block precedes `通用规则` block); explicit medical implicit-negative patterns enumerated (`既往史：无特殊`, `未见异常`, `无明显异常`, plus `个人史/系统回顾/病史` variants); `forbidden_inference_flags` / `family_context` rules preserved; clause-bounded negation rule preserved (matches the 2026-05-17 `_positive_span` fix); `allowed_codes` is the only valid code source. New `backend/tests/test_evidence_first_prompt.py` (8 tests) pins the prompt version, the structural ordering of policy-vs-generic blocks, the implicit-negative pattern coverage, family-context warnings, clause-boundary rules, allowed_codes locking, no per-case data leak (cache stability), and byte-stability across calls. Backend tests 318 → 326. Rule-only baseline (1.0/54) unchanged.

### done PLAN-llm-provider-phase-2

- Goal: ROADMAP E1-011 Phase 2. Implement `OpenAICompatibleChatProvider.collect_evidence` so DeepSeek / OpenRouter / Moonshot / Qwen / Z.AI / Azure / Custom actually call `/chat/completions` with `response_format: json_object` and the evidence-first JSON schema.
- Outcome: real implementation lands. New `_chat_completions_evidence_first_payload` helper in `services/llm_provider/payloads.py` with byte-stable cacheable prefix (system prompt + extraction rules + JSON schema descriptor). Adapter degrades gracefully to `local_collect_evidence_fallback` on permanent error, missing response, or malformed JSON; rate-limit / timeout enters per-key cooldown. Process-local exposure-policy override (`set_runtime_exposure_policy_override`) added so the eval bootstrap can opt into full-context exposure for synthetic fixtures without modifying the medical schema's `safe_evidence_only` default. New `--unsafe-eval-allow-remote-context` flag on `bootstrap-eval-fixtures.py` activates the override for one process. New `mock_general_llm.json` baseline at `accuracy=0.9259` (50/54), `input_tokens=72372`, `output_tokens=18757` against DeepSeek v4-flash. The 4 failures cluster on `eval-mock-007` implicit-negative (`既往史：无特殊`); that pattern is the E1-001 prompt-rewrite target.
- Acceptance commands: `python scripts/check-llm-connectivity.py --profile-id deepseek_v4_flash`; `Remove-Item var\storage\llm_cache -Recurse -Force; python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --unsafe-eval-allow-remote-context --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: `OpenAICompatibleChatProvider.collect_evidence` calls `chat.completions.create` and parses the response into `EvidenceCandidate` objects; mock_general_llm baseline records non-zero input/output tokens; the bootstrap WARN line no longer fires when full-context override is active; Phase 1 contract tests still pass; rule-only baseline `mock_general.json` (1.0/54) is unchanged. The legacy DPAPI-stored DeepSeek key still drives the call (`fingerprint=sk...34`); `.env` is back to its pre-2026-05-18 state.

### done PLAN-llm-provider-phase-1

- Goal: ROADMAP E1-011 Phase 1. Make `collect_evidence` `@abstractmethod` on `SemanticExtractionProvider`. Move the previous default body to `local_collect_evidence_fallback(document_context, fields)`. Every concrete adapter declares an explicit override. Add a contract test that asserts no adapter inherits the default and every catalog provider value resolves to an adapter.
- Acceptance commands: `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: `SemanticExtractionProvider.collect_evidence` and `extract_group` are both `@abstractmethod`; `OpenAIResponsesProvider` keeps its real implementation; `OpenAICompatibleChatProvider`, `AnthropicMessagesProvider`, `GoogleGeminiProvider` each declare an explicit `collect_evidence` that returns `local_collect_evidence_fallback(...)` (Phase 2 / 3 will replace these with real upstream calls); `ConservativeLocalProvider` declares its own real implementation. New `backend/tests/test_provider_contracts.py` (15 tests) pins the rules. Existing 3 stub providers in test files (`_AlwaysFailingProvider` ×2 and `CountingProvider`) gained their own `collect_evidence` overrides. AGENTS.md "Architecture Boundaries" gains the explicit-delegation rule. `docs/DECISIONS.md` 2026-05-18 records "Default-inheritance shim for collect_evidence is forbidden". Mock_general rule baseline (1.0/54) and LLM baseline (1.0/54 with `input_tokens=0`) both unchanged on disk; the WARN line in the bootstrap script still fires because adapters explicitly chose to delegate. 318 backend tests pass (303 prior + 15 new contract tests).

### done PLAN-llm-baseline-bootstrap

- Goal: Establish the LLM-assisted baseline tooling for `mock_general`. Add `--provider {rule,llm}` to the bootstrap script so the rule-only baseline (`mock_general.json`) and the LLM-assisted baseline (`mock_general_llm.json`) coexist.
- Outcome: `--provider llm` flag wired through `bootstrap-eval-fixtures.py` and `.ps1`. Baseline file path now suffix-aware: `mock_general.json` for rule, `mock_general_llm.json` for llm. Per-case provider construction so usage counters do not aggregate. Pre-flight `_verify_llm_key` reports a redacted profile + key fingerprint or refuses to run with exit code 4. The provider kind is tagged into the on-disk baseline (`profile.semantic_provider_kind = "llm"|"rule"`).
- Surprise discovery (recorded as ROADMAP E1-011): when run against the active DeepSeek profile the LLM baseline reported `input_tokens=0`. Root cause: `OpenAICompatibleChatProvider` does not override `SemanticExtractionProvider.collect_evidence`, so the evidence-first path silently falls back to local rule extraction. The script now emits a clear WARN line directing readers to E1-011 whenever this happens. The `mock_general_llm.json` baseline file (zero token, accuracy 1.0) is still committed because it is honest evidence of the gap and the next E1-001 / E1-002 / E1-011 commits will diff against it.
- Acceptance commands: `python scripts/check-llm-connectivity.py --profile-id deepseek_v4_flash`; `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: bootstrap script supports `--provider` with `rule` and `llm`; LLM baseline JSON committed; ROADMAP E1-011 added to track the adapter implementation gap; AGENTS.md unchanged (the rule contract still applies; this commit only adds tooling and surfaces a tracked gap).

### done E1-005-synonym-widening Close eval-mock-008 recall gaps and add LLM connectivity check

- Goal: Close the 2 known recall gaps surfaced by the `eval-mock-008` challenge case by widening the schema synonym lists for `hypertension_history` and `drinking_history`. Add a connectivity check script that verifies the active LLM provider profile is reachable without ever printing the API key value. Configure the deepseek_v4_flash profile with the user-provided API key under explicit time-limited authorization (see `docs/DECISIONS.md` 2026-05-18 entry on chat-pasted keys).
- Acceptance commands: `python scripts/check-llm-connectivity.py`; `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: Schema synonyms widened (`hypertension_history` adds `血压偏高 / 血压增高 / 血压高 / BP高`; `drinking_history` adds `嗜酒 / 喝酒 / 酗酒`); baseline regenerated at `accuracy=1.0` (54/54); the two pinned regression tests inverted from MISSING to PASS; `scripts/check-llm-connectivity.py` and `.ps1` exist with redacted key reporting and a `model_calls` ledger row; `test_model_profiles.py` made resilient to settings-driven default profile via monkeypatch; .env configured with deepseek key (gitignored). Old DPAPI-stored key backed up to `var/storage/provider_secrets.json.bak-2026-05-18` so the .env key is the active credential.

### done PLAN-field-coverage-and-ocr-postprocessing-research

- Goal: Produce two research/planning docs that scope the next phases of precision work. `docs/FIELD_COVERAGE.md` inventories every export-template column, the current `mock_general` baseline coverage (9 of 22 schema fields), and a 7-phase fixture expansion plan. `docs/OCR_POST_PROCESSING.md` maps the open-source landscape (pycorrector, ChineseErrorCorrector, CBLUE, PromptCBLUE, SNOMED CT/ICD-10-CN, MinerU, Docling) to EYEX's pipeline stages, with license verification and explicit non-copy boundaries.
- Acceptance commands: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`. Doc-only commit.
- Done condition: both docs exist; AGENTS.md documentation map references them; ROADMAP gains E1-009 (eval-only OCR character correction diagnostic via pycorrector) and E1-010 (multi-phase mock_general fixture expansion) backed by FIELD_COVERAGE phases A-G.

### done PLAN-mock-general-challenge-case

- Goal: Add a "challenge" fixture (`eval-mock-008`) that uses real-world non-standard phrasings missing from the schema synonyms list. The case must lower the rule-only baseline below 1.0 so that any future E1 task targeting `mock_general` has a measurable recall gap to close.
- Acceptance commands: `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: `eval-mock-008.txt` exists; YAML gold reflects the human-correct answer (not what the current rule path can recover); baseline regenerated at `accuracy=52/54≈0.9630` with `auto_accept_precision=1.0` (no false positives, only missed positives); two new regression tests in `test_evidence_first_extraction.py` pin the `'血压偏高' → MISSING` and `'嗜酒' → MISSING` behavior so the precision-task lifecycle (fixture/baseline/test triple update in one commit) is enforced.

### done PLAN-mock-general-coverage-expansion

- Goal: Widen `mock_general` from 5 to 7 synthetic fixtures so the precision baseline exercises code paths that the original set did not touch: heart_disease_history positive, stroke_history positive, implicit-negative (`既往史：无特殊`), and the `excluded_sections: [家族史]` guard against family-history leakage.
- Acceptance commands: `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: `eval-mock-006.txt` and `eval-mock-007.txt` exist with the matching gold cases in the YAML; baseline regenerated at `accuracy=1.0` on 48/48 (up from 32/32) without metric regression on the original 5 cases; `field_tags` extended to include `heart_disease_history` and `stroke_history`; `test_fixture_count_matches_committed_baseline` pins the 7-case ledger so future drift is explicit.

### done E1-005-clause-boundary Positive history span clipped at sentence terminators

- Goal: Close the 3 known positive-history recall gaps in the `mock_general` baseline by fixing `_positive_span` in `services/evidence_first.py`, which incorrectly suppressed valid positive evidence whenever the next clause negated a different field. Companion regression tests pin the corrected clause-boundary behavior so future refactors cannot reintroduce the leak.
- Acceptance commands: `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: `services/evidence_first.py:_positive_span` clips left and right windows at `。 ； ; \n` and only consults left-side negation; two new regression tests in `test_evidence_first_extraction.py` cover `高血压病史10年。否认糖尿病史。` and `吸烟史20年，每日10支。否认饮酒史。`; baseline regenerated at `accuracy=1.0` (32/32), `auto_accept_precision=1.0`, `evidence_coverage=1.0`, `unknown_misfill_rate=0.0`; the `test_baseline_file_is_present_and_well_formed` floor is raised from 0.90625 to 1.0 in the same commit.

### done PLAN-mock-general-baseline

- Goal: Establish a deterministic precision baseline for `mock_general` so every E1 task has a real before/after comparison line. Add 5 synthetic Chinese inpatient case fixtures, expand the evaluation profile gold cases to cover demographics + chronic disease + lifestyle fields, ship a bootstrap script that processes fixtures and writes the baseline JSON, and gate the baseline with a contract test.
- Acceptance commands: `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline`; `python -m pytest backend\tests\test_eval_fixtures.py`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: `config/evaluation_profiles/fixtures/mock_general/eval-mock-00{1..5}.txt` exist; `config/evaluation_profiles/mock_general.yaml` declares 5 gold cases with stable IDs; `scripts/bootstrap-eval-fixtures.py` and `.ps1` exist with documented exit codes; `config/evaluation_profiles/baselines/mock_general.json` is the committed precision baseline (accuracy 0.90625, auto_accept_precision 1.0, evidence_coverage 1.0, unknown_misfill_rate 0.0); `backend/tests/test_eval_fixtures.py` enforces fixture-gold sync, baseline schema, and reproducibility through bootstrap+eval.

### done E0-008 Field-extraction eval runner

- Goal: Build a CLI runner for `config/evaluation_profiles/*.yaml` analogous to `scripts/run-ocr-eval.py`. The runner reports per-field precision, recall, exact-match, unknown-rate, and token cost with a stable schema so before/after diffs are mechanical. This unblocks every E1 precision task.
- Acceptance commands: `python -m pytest backend\tests\test_extraction_eval.py`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Done condition: `backend/app/services/extraction_eval.py` is the canonical scoring service; FastAPI `/api/evals/*` routes delegate to it; `scripts/run-extraction-eval.py` and `.ps1` exist with documented exit codes (0 ok, 2 blocked, `--allow-blocked` overrides); `backend/tests/test_extraction_eval.py` covers schema, scoring, missing-case, summary, and CLI exit codes (9 tests pass); side effect routes.py dropped from 810 to 653 lines, clearing one governance warning.

### done PLAN-write-architecture-doc

- Goal: Produce `docs/ARCHITECTURE.md` as the authoritative description of the EYEX main pipeline.
- Acceptance commands: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`. Doc-only commit.
- Done condition: `docs/ARCHITECTURE.md` exists with full pipeline, layering, services map, boundary contracts, data flow detail, and known boundary frictions linked to PLAN tasks. AGENTS.md documentation map updated to remove the `(planned)` tag.

### done PLAN-write-roadmap

- Goal: Produce `docs/ROADMAP.md` with phased optimization tasks for precision in OCR, layout, evidence collection, and LLM prompts. Use `E0-NNN` for governance and structural prerequisites, `E1-NNN` for borrow-from-open-source improvements, `E2-NNN` for product-grade precision and throughput.
- Acceptance commands: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`. Doc-only commit.
- Done condition: `docs/ROADMAP.md` exists with E0/E1/E2 phases (8 + 8 + 6 tasks). Every entry carries a stable ID, an eval-profile-anchored acceptance line, and prerequisite IDs. AGENTS.md documentation map updated to remove the `(planned)` tag.

### done PLAN-write-reference-projects

- Goal: Produce `docs/REFERENCE_PROJECTS.md`, the open-source reference registry.
- Acceptance commands: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`. Doc-only commit.
- Done condition: `docs/REFERENCE_PROJECTS.md` exists with PaddleOCR, MinerU, Docling, olmOCR, Marker, dots.ocr, Unstructured, Instructor, Outlines, LiteLLM, Continue, OpenClaw, Cline, Open WebUI, Dify. Every entry verifies license against the upstream URL, names today's EYEX use, lists what is borrowed by reference, and states the non-copy boundary. License-restricted projects (MinerU OSL with additions, Marker GPL-3.0, Open WebUI, Dify) flagged as ideas-only without a `docs/DECISIONS.md` approval. AGENTS.md documentation map updated to remove the `(planned)` tag.

### done Triage and merge the in-progress ChartLens upgrade into dev

- Goal: Drive `git status --short` to empty by either committing or discarding the ~93 in-progress files that had been sitting on `dev` for the full ChartLens upgrade.
- Acceptance commands: `git status --short` empty; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Risk: Cross-subsystem changes (backend services, OCR engine modules, frontend, config, scripts, tests) could not be split without each subset failing tests in isolation.
- Trigger: AGENTS.md "long-running branches with > 60 dirty files" rule.
- Done condition: Landed as one explicit integration commit on `dev` with `.gitignore` housekeeping and a follow-up perf_counter timing fix; documented in this entry.

### done Add dev branch workflow for personal Codex development

- Goal: Keep the full ChartLens upgrade on `dev`, and keep future Codex work scoped to task branches before it reaches `dev` or `main`.
- Out of scope: Do not introduce a heavyweight issue tracker or team review process.
- Acceptance commands: `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`
- Risk: Without branch and verification rules, Codex sessions can mix unrelated changes and make rollback difficult.
- Trigger: Before uploading the project to GitHub.
- Done condition: `AGENTS.md`, `docs/CODEX_WORKFLOW.md`, and `docs/DECISIONS.md` define `main`, `dev`, and `codex/<goal>` responsibilities.

### done Delete OCR runtime engine override

- Goal: Make OCR engine order come only from `config/ocr_profiles/*.yaml`.
- Out of scope: No OCR engine behavior change beyond removing the old override path.
- Acceptance commands: `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`
- Risk: Existing local `.env` may still contain ignored old variables, but app code no longer reads them.
- Trigger: Cleanup after project governance review.
- Done condition: Application code no longer reads the old OCR engine override environment variable.

### done Add personal CI and frontend test entrypoint

- Goal: Make backend tests, frontend tests, and frontend build repeatable locally and in CI.
- Out of scope: No heavy lint/format stack yet.
- Acceptance commands: `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`
- Risk: CI is intentionally minimal and does not replace local high-risk eval runs.
- Trigger: Need for Codex-friendly verification gate.
- Done condition: `.github/workflows/ci.yml` and `npm test` exist and pass.
