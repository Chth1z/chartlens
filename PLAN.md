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
- Trigger: AGENTS.md "the next task touching this file must include a split" — `pipeline.py` crossed 500 lines on 2026-05-18 with E1-005 rule_pre_accepted. Any further pipeline-touching feature work must do the split first.
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

The five most recent done entries stay here in detail. Older done entries live in `docs/PLAN_HISTORY.md` (rotation rule: AGENTS.md "Documentation Maintenance"). When a new done entry lands, the oldest entry in this section moves to `docs/PLAN_HISTORY.md` as a one-paragraph summary plus a link to its DECISIONS anchor when one exists.

### done E1-005 rule_pre_accepted shortcut (2026-05-18)

- Goal: ROADMAP E1-005. Wire the long-open `rule_pre_accepted` shortcut in `_extract_document_evidence_first` so phase-1 fields whose group has `semantic_strategy: rule_shortcut` AND `rule_shortcut_extract` returns confidence >= 0.95 bypass the LLM evidence-first chain entirely. Tag bypassed candidates with `acceptance_reason="rule_pre_accepted"`, `provenance.source="rule_shortcut"`, `provenance.skipped_llm=True`, `provenance.decision_status="PASS"`. Close the `eval-mock-003 / age` LLM gap surfaced by E1-010 Phase A.
- Outcome: implemented as a partition step at the top of `_extract_document_evidence_first`. `rule_shortcut_candidates` collects pre-accepted hits via `rule_candidate.model_copy(update=...)`; `llm_fields` is what gets passed to `evidence_provider.collect_evidence` and downstream stages. After LLM stages, `rule_shortcut_candidates` is merged in (rule wins). Export gate preserved by stamping `provenance.decision_status="PASS"` on rule candidates. Backend tests rise 342 → 343. LLM-assisted `mock_general` baseline rises from 0.9722 (70/72) to 0.9861 (71/72) on the chosen baseline run; across 5 cache-cleared runs the spread is 70-72/72 with `age` deterministically PASS in every run. Token cost on the chosen run is 73,037 input / 19,743 output.
- Anchor: `docs/DECISIONS.md` 2026-05-18 "rule_pre_accepted shortcut bypasses LLM for high-confidence rule_shortcut groups"; AGENTS.md "Architecture Boundaries".

### done PLAN-mock-general-phase-A (2026-05-18)

- Goal: ROADMAP E1-010 Phase A. Extend the `mock_general` baseline to cover `hospital` (string free-text) and `urban_residence` (enum derived from address pre-redaction). Add one urban-address fixture, one rural-address fixture, anchor the unknown path by extending an existing fixture's gold.
- Outcome: rule-only baseline rises from 1.0/54 to 1.0/72 on 10 fixtures. New `eval-mock-009` (urban: `南京市鼓楼区五一路` → `urban_residence=2`, `海安市第三人民医院`) and `eval-mock-010` (rural: `海安县曲塘镇五星村3组` → `urban_residence=1`, `海安县中医院`); `eval-mock-005` gold extended to anchor the unknown path. Privacy boundary verified by new parametrized test `test_phase_a_address_redaction_holds_in_deidentified_ir`: original `家庭住址` lines collapse to `[REDACTED]`; only the safe `是否城市判定` derivation block carries forward. The LLM-assisted baseline temporarily drops to 0.9722 (70/72) because the wider fixture set surfaces two unrelated honest LLM gaps; both become next-up targets for the open `rule_pre_accepted` shortcut and a v3 prompt rewrite.
- Anchor: `docs/FIELD_COVERAGE.md` Phase A section; ROADMAP E1-010 Phase A.

### done PLAN-llm-provider-phase-3 (2026-05-18)

- Goal: ROADMAP E1-011 Phase 3. Real `collect_evidence` for `AnthropicMessagesProvider` and `GoogleGeminiProvider`. New `services/llm_provider/registry.py` replaces the if/elif chain in `fallback._provider_for_profile` with a data-driven dispatch table.
- Outcome: every concrete LLM adapter now has a real evidence-first remote call. Anthropic posts to `/v1/messages` with the byte-stable evidence-first system prompt + JSON schema descriptor. Gemini posts to `/v1beta/models/<model>:generateContent` with `responseSchema` translated from the JSON Schema fragment via `_gemini_response_schema` (drops `additionalProperties`, folds `type: ['x', 'null']` into `nullable: true`, uppercases types per OpenAPI 3.0). Privacy boundary preserved: both adapters honor `safe_evidence_only` and degrade to `local_collect_evidence_fallback` with `remote_skipped_reason=remote_full_context_disabled`. Registry knows 4 adapter kinds with declared `llm_mode` sets. Backend tests 326 → 340 (14 new in `test_provider_phase_3.py`).
- Anchor: `docs/LLM_PROVIDER_REFACTOR.md` Phase 3; AGENTS.md "Architecture Boundaries" explicit-delegation rule.

### done E1-001 evidence-first prompt rewrite (2026-05-18)

- Goal: Rewrite `_evidence_first_system_prompt` so it teaches the LLM to honor field-level `evidence_policy.implicit_negative_policy` and `allowed_codes` instead of falling back to a generic "missing means unknown" default. Close the 4 known LLM failures on `eval-mock-007` (`既往史：无特殊` interpreted as unknown rather than 0).
- Outcome: mock_general LLM baseline rises from 0.9259 to 1.0 (50/54 → 54/54) AND token cost drops from 72372/18757 to 37792/11170 (-47.8% input, -40.4% output). Cacheable prefix is byte-stable; `EVIDENCE_FIRST_PROMPT_VERSION` bumped from `eyex-evidence-first-v1` to `eyex-evidence-first-v2` so cached results from the old prompt auto-invalidate. New `backend/tests/test_evidence_first_prompt.py` (8 tests). Backend tests 318 → 326. Open follow-up: 2026-05-18 E1-010 Phase A surfaced an `evidence_text` paraphrase gap that v3 must close (tracked in active todo `PLAN-llm-evidence-text-substring`).
- Anchor: `docs/DECISIONS.md` 2026-05-18 "Evidence-first prompt promotes field-level policy above generic rules"; ROADMAP E1-001.

### done PLAN-llm-provider-phase-2 (2026-05-18)

- Goal: ROADMAP E1-011 Phase 2. Implement `OpenAICompatibleChatProvider.collect_evidence` so DeepSeek / OpenRouter / Moonshot / Qwen / Z.AI / Azure / Custom call `/chat/completions` with `response_format: json_object` and the evidence-first JSON schema.
- Outcome: real implementation lands. New `_chat_completions_evidence_first_payload` helper in `services/llm_provider/payloads.py` with byte-stable cacheable prefix. Adapter degrades gracefully to `local_collect_evidence_fallback` on permanent error, missing response, or malformed JSON; rate-limit / timeout enters per-key cooldown. Process-local exposure-policy override (`set_runtime_exposure_policy_override`) added so the eval bootstrap can opt into full-context exposure for synthetic fixtures via the new `--unsafe-eval-allow-remote-context` flag without modifying the medical schema's `safe_evidence_only` default. New `mock_general_llm.json` baseline at `accuracy=0.9259` (50/54), `input_tokens=72372`, `output_tokens=18757` against DeepSeek v4-flash. The 4 failures cluster on `eval-mock-007` implicit-negative — the E1-001 prompt-rewrite target.
- Anchor: `docs/LLM_PROVIDER_REFACTOR.md` Phase 2; ROADMAP E1-011.

## Older Done Entries

Rotated to `docs/PLAN_HISTORY.md` per AGENTS.md "Documentation Maintenance":

- 2026-05-18: PLAN-llm-provider-phase-1; PLAN-llm-baseline-bootstrap; E1-005-synonym-widening; PLAN-field-coverage-and-ocr-postprocessing-research.
- 2026-05-17: PLAN-mock-general-challenge-case; PLAN-mock-general-coverage-expansion; E1-005-clause-boundary; PLAN-mock-general-baseline; E0-008 field-extraction eval runner; PLAN-write-architecture-doc; PLAN-write-roadmap; PLAN-write-reference-projects.
- 2026-04-30: ChartLens upgrade triage; dev branch workflow; OCR runtime engine override removal; CI and frontend test entrypoint.
