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

### todo PLAN-split-styles-css

- Goal: Split `frontend/src/styles.css` (currently 3211 lines) into feature-scoped stylesheets that match the `frontend/src/features/` layout. Aim for ≤ 800 lines per file. Suggested split: a base/reset module, an evidence panel module, a settings module, a diagnostics module, and a review module. Use CSS imports or component-level imports, not a runtime concatenation step.
- Out of scope: No visual change. No design-system or Tailwind migration in this task.
- Acceptance commands: `cd frontend; npm test; npm run build`. Manual smoke: open the app, walk through cases, settings, diagnostics, and review and confirm visuals are unchanged.
- Risk: Selectors that depend on rule order can break when split across files; verify by running the build and a smoke pass.
- Trigger: AGENTS.md soft trigger at 500 lines plus hard governance warning at 800 lines; the file is currently the largest in the repository.
- Done condition: Each new stylesheet ≤ 800 lines, the governance scan reports no large-file warning for `frontend/src/styles.css`, and the existing 9 frontend tests pass.

### todo PLAN-llm-provider-phase-1

- Goal: ROADMAP E1-011 Phase 1. Make `collect_evidence` `@abstractmethod` on `SemanticExtractionProvider`. Move the current default body to `local_collect_evidence_fallback(document_context, fields)` exported from `services/llm_provider/types.py`. Every concrete adapter (`OpenAIResponsesProvider` keeps real impl; `OpenAICompatibleChatProvider` / `AnthropicMessagesProvider` / `GoogleGeminiProvider` / `ConservativeLocalProvider` all gain explicit overrides; the LLM ones return `local_collect_evidence_fallback(...)` for now). Add `tests/test_provider_contracts.py` asserting no adapter inherits the default and every `provider` value in `config/model_providers/mainstream.yaml` resolves through `_provider_for_profile`. AGENTS.md gains the rule "Every concrete `SemanticExtractionProvider` adapter must explicitly choose between calling its remote API and delegating to `local_collect_evidence_fallback`."
- Out of scope: No new LLM call. No prompt change. No accuracy change. Phase 2 / 3 work.
- Acceptance commands: `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`. The `mock_general_llm.json` baseline still records `input_tokens=0` (because adapters explicitly chose to delegate); the WARN line still fires; both are now expected, pinned behavior.
- Risk: Very low. This is a refactor that names an existing behavior with no on-disk metric change. The contract test is the ratchet that prevents the gap from re-hiding.
- Trigger: ROADMAP E1-011 Phase 1.
- Done condition: `SemanticExtractionProvider.collect_evidence` is `@abstractmethod`; every concrete adapter has an explicit override; the contract test exists; AGENTS.md "Architecture Boundaries" gains the explicit-delegation rule; DECISIONS.md gains a new entry "Default-inheritance shim for collect_evidence is forbidden"; rule-only baseline (1.0/54) is unchanged.

### todo PLAN-llm-provider-phase-2

- Goal: ROADMAP E1-011 Phase 2. Implement `OpenAICompatibleChatProvider.collect_evidence` so DeepSeek / OpenRouter / Moonshot / Qwen / Z.AI / Azure / Custom actually call their `/chat/completions` endpoint with `response_format: json_object` and the evidence-first JSON schema. New `_chat_completions_evidence_first_payload` mirrors `_responses_evidence_first_payload`. Cacheable prefix (system prompt + extraction rules + JSON schema descriptor) is byte-stable for DeepSeek prompt-cache hits. Malformed JSON degrades to `local_collect_evidence_fallback` instead of crashing. New test stubs an OpenAI-compatible HTTP server, asserts payload shape and graceful degradation.
- Out of scope: Anthropic / Gemini implementations (Phase 3). Prompt content rewrite (E1-001). Retry-with-validation-feedback (E1-003). New fixtures.
- Acceptance commands: `python scripts/check-llm-connectivity.py --profile-id deepseek_v4_flash`; `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Risk: Medium. Real network round trip per fixture during baseline regenerate. Rate limits possible. Mitigations: existing `_api_keys_for_attempts` cooldown; client-side cache absorbs reruns; second consecutive run should hit DeepSeek server-side prompt cache.
- Trigger: After Phase 1.
- Done condition: `mock_general_llm.json` baseline records `input_tokens > 0`, `output_tokens > 0`, `cost_usd > 0`; accuracy stays at 1.0/54 (or higher); a second consecutive run records `cached_input_tokens > 0`; the bootstrap WARN line is gone; new contract tests pass.

### todo PLAN-llm-provider-phase-3

- Goal: ROADMAP E1-011 Phase 3. Implement `AnthropicMessagesProvider.collect_evidence` (system + messages + tool_use shape) and `GoogleGeminiProvider.collect_evidence` (systemInstruction + responseSchema shape). Extract `services/llm_provider/router.py` with separate `with_retries()` and `with_fallbacks()` methods (LiteLLM pattern). Replace `fallback._provider_for_profile` if/elif with `services/llm_provider/registry.py`. Document or remove the legacy `extract_group` path now that no committed schema selects it.
- Out of scope: Streaming. Multi-modal page-image input beyond what `_responses_evidence_first_payload` already gates on `policy.allow_page_images`. Provider catalog YAML changes.
- Acceptance commands: same as Phase 2 plus a per-adapter parametrized run with at least one model_profile from each adapter family in CI mock mode (no real API key required for the mock-server tests).
- Risk: Higher than Phase 2 because every adapter changes. Mitigation: explicit-delegation shim from Phase 1 still serves as fallback for any specific adapter that hits a bug; registry coverage test prevents adding a new provider without an adapter wiring.
- Trigger: After Phase 2.
- Done condition: every adapter has a real `collect_evidence`; registry-based dispatch; `Router` class separates retry from fallback; `extract_group` is either removed or gated behind a documented non-default extraction strategy; ROADMAP E1-011 marked done; the way is clear for E1-001 / E1-002 / E1-003.

### todo PLAN-mock-general-phase-A

- Goal: ROADMAP E1-010 Phase A. Extend the `mock_general` baseline to cover the two demographics fields currently outside the 8-case set: `hospital` (string free-text) and `urban_residence` (enum derived from address pre-redaction). Reuse one existing fixture by adding the `医院: XXX市XXX医院` line and a sample address; add one new fixture with no address to verify `urban_residence` rule does not over-fire and stays unknown when the source has no usable signal.
- Out of scope: No change to schema synonyms. No new schema field. No phase B-G work.
- Acceptance commands: `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline`; `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Risk: `urban_residence` runs through `pre_redaction_derivations`, which executes BEFORE deidentification. A malformed fixture address could leak into the de-identified DocumentIR if the rule misfires. Verify the resulting `DocumentIR` blocks contain only the safe derived block, not the original address. The two new (or modified + new) fixtures must follow `docs/DECISIONS.md` 2026-04-30 "Address-derived fields use safe local derivations".
- Trigger: `mock_general` is the current precision baseline; E1-010 phases close the field-coverage gap surfaced by `docs/FIELD_COVERAGE.md`.
- Done condition: at least one fixture asserts `hospital` non-empty; at least one fixture asserts `urban_residence` with a recognized code; at least one fixture asserts `urban_residence=unknown` to verify the unknown path; `test_eval_fixtures.py::test_fixture_count_matches_committed_baseline` updated; baseline JSON regenerated; `docs/ROADMAP.md` Active Baselines row updated; `docs/FIELD_COVERAGE.md` Phase A status moved from todo to done.

### todo Decide application/ vs services/ flat layout

- Goal: Resolve the dev-vs-main divergence. Either restore the `backend/app/application/` layer that exists on `main`, or formalize `backend/app/services/` subpackages with hard size limits in AGENTS.md. The chosen direction is recorded in `docs/DECISIONS.md` before any code in `services/` or `application/` is reorganized.
- Out of scope: No business behavior change. No new feature in this task.
- Acceptance commands: `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`.
- Risk: Without a recorded decision, future split tasks (provider, pipeline, OCR boundary) keep blocked by an absent layer; pipeline.py keeps mixing orchestration, error formatting, worker pool, quality summary.
- Trigger: After Triage 97 dirty files completes.
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
