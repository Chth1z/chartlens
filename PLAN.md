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

### todo Add database migration baseline before schema expansion

- Goal: Replace the manual `Base.metadata.create_all(...)` plus ad hoc `_ensure_sqlite_columns` `ALTER TABLE` path with an Alembic migration baseline. Startup runs `alembic upgrade head`. Fresh DB and existing DB go through the same path.
- Out of scope: No move to Postgres. No schema additions in this task.
- Acceptance commands: `python -m pytest backend\tests`; manually verify a fresh `var/storage/eyex.sqlite3` is created on first run and an existing one upgrades without manual SQL.
- Risk: Manual `create_all` and ad hoc `ALTER` will become unsafe as review, eval, and job history grow.
- Trigger: Before adding the next persistent table or non-null column.
- Done condition: `alembic` is in `requirements.txt`, baseline migration captures all 7 current tables, startup runs migrations, and the manual `_ensure_sqlite_columns` shim is deleted.

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

### done PLAN-split-styles-css (2026-05-22)

- Goal: Split `frontend/src/styles.css` (3726 lines) into feature-scoped stylesheets ≤ 800 lines each.
- Outcome: Pure structural refactor, no visual change. Split into 10 files under `frontend/src/styles/`: `base.css` (109), `layout.css` (428), `cases.css` (182), `evidence.css` (256), `document.css` (785), `review.css` (429), `settings.css` (592), `providers.css` (269), `diagnostics.css` (253), `components.css` (422). Original `styles.css` replaced with a 10-line barrel using CSS `@import`. Updated `ocrSourceDebug.test.ts` to read from the correct split file. All 9 frontend tests pass; build succeeds; governance scan passes with no large-file warnings.
- Anchor: AGENTS.md 500/800-line ceiling rule.

### done Decide application/ vs services/ flat layout (2026-05-19)

- Goal: Resolve the pending architecture decision. Either restore `backend/app/application/` or formalize `backend/app/services/` subpackages.
- Outcome: Decision recorded in `docs/DECISIONS.md` 2026-05-19: formalize `services/` subpackages as the canonical backend layout. No `application/` layer. Complex subsystems get subpackage directories (`llm_provider/`, `ocr_engine/`); simpler modules use flat-file-with-prefix pattern (`pipeline_*.py`). Hard size limits from AGENTS.md apply. This unblocks E0-004 (provider split), E0-005 (OCR boundary), E0-006 (model_providers split).
- Anchor: `docs/DECISIONS.md` 2026-05-19 "Formalize services/ subpackages as the canonical backend layout".

### done PLAN-split-pipeline.py (2026-05-21)

- Goal: Split `backend/app/services/pipeline.py` (526 lines) into smaller modules to satisfy the AGENTS.md 500-line soft trigger.
- Outcome: Pure refactor, no behavior change. Split into `pipeline.py` (300 lines, orchestrator), `pipeline_evidence_first.py` (235 lines, evidence-first extraction flow), `pipeline_quality.py` (58 lines, quality summary helpers), `pipeline_errors.py` (17 lines, error formatting). All 344 backend tests pass; rule baseline 1.0 (80/80); LLM baseline 1.0 (80/80); frontend tests and build pass; governance scan passes (no large-file warning for any pipeline file).
- Anchor: AGENTS.md 500-line soft trigger rule.

### done PLAN-mock-general-phase-B (tumor_history, E1-010, 2026-05-20)

- Goal: ROADMAP E1-010 Phase B. Extend `mock_general` to cover `tumor_history`.
- Outcome: Rule-only baseline rises from 1.0 (72/72) to 1.0 (80/80) on 11 fixtures. New `eval-mock-011` (explicit positive: `恶性肿瘤病史3年` → `tumor_history="1"`) plus extended gold on `eval-mock-007` (implicit-negative: `既往史：无特殊` → `tumor_history="0"`). LLM-assisted baseline also 1.0 (80/80); token cost 26,406 input / 7,946 output. `mock_general.yaml` `field_tags` includes `tumor_history`; `test_eval_fixtures.py` fixture count updated to 11. Coverage: 12/22 schema fields.
- Anchor: `docs/FIELD_COVERAGE.md` Phase B; ROADMAP E1-010 Phase B.

### done PLAN-llm-evidence-text-substring (E1-001 v3, 2026-05-19)

- Goal: Tighten `_evidence_first_system_prompt` and the evidence-first JSON schema so that `evidence_text` MUST be a contiguous substring of the cited block's text, and `normalized_code` for free-text/numeric fields MUST be the actual extracted value, never a type-class placeholder like `'text'` or `'integer'`. Bump `EVIDENCE_FIRST_PROMPT_VERSION` to `eyex-evidence-first-v3`.
- Outcome: Two new prompt sections added to the cacheable prefix: "evidence_text 必须为引用 block 的连续子串" (with the `否认高血压病、糖尿病、冠心病等病史` verbatim-clause example) and "normalized_code 不是类型占位符" (with hospital/numeric concrete examples). JSON schema `evidence_text` and `normalized_code` fields gain `description` strings mirroring the rules. LLM-assisted `mock_general` baseline rises from 0.9861 (71/72) to 1.0 (72/72) deterministically — 3/3 cache-cleared runs hit 1.0. Token cost on the committed run: 52,674 input / 12,985 output (vs. prior 73,037/19,743 on the E1-005 chosen run; -28% input, -34% output). Backend tests 343 → 344 (new `test_v3_prompt_requires_substring_evidence_text`). Cacheable prefix byte-stability preserved (test passes).
- Anchor: ROADMAP E1-001 outcome line updated; `docs/FIELD_COVERAGE.md` Phase A note updated.

## Older Done Entries

Rotated to `docs/PLAN_HISTORY.md` per AGENTS.md "Documentation Maintenance":

- 2026-05-22: E1-005 rule_pre_accepted shortcut (2026-05-18).
- 2026-05-19: PLAN-mock-general-phase-A (2026-05-18).
- 2026-05-21: PLAN-llm-provider-phase-3 (2026-05-18).
- 2026-05-20: E1-001 evidence-first prompt rewrite (2026-05-18).
- 2026-05-18: PLAN-llm-provider-phase-1; PLAN-llm-baseline-bootstrap; E1-005-synonym-widening; PLAN-field-coverage-and-ocr-postprocessing-research.
- 2026-05-17: PLAN-mock-general-challenge-case; PLAN-mock-general-coverage-expansion; E1-005-clause-boundary; PLAN-mock-general-baseline; E0-008 field-extraction eval runner; PLAN-write-architecture-doc; PLAN-write-roadmap; PLAN-write-reference-projects.
- 2026-04-30: ChartLens upgrade triage; dev branch workflow; OCR runtime engine override removal; CI and frontend test entrypoint.
