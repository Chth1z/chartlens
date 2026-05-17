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
