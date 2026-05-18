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

### done PLAN-split-ocr (2026-05-19)

- Goal: Reduce the 532-line `backend/app/services/ocr.py` (above the AGENTS.md 500-line soft trigger) to a focused subpackage where each module ≤ 300 lines.
- Outcome: Pure structural refactor, no behavior change. Replaced the monolithic file with `backend/app/services/ocr/`: `__init__.py` (13) re-exports the public API (`build_document_ir`, `file_sha256`) plus the test-monkeypatch surface (`extract_with_intelligent_ocr`, `_extract_pdf_text_pages`, `_ocr_cache_path`, `_ocr_extractor_cache_fingerprint`, `_extract_blocks`, `_extract_pdf_blocks`, `_extract_pdf_ocr_pages`, `_call_intelligent_ocr`); `blocks.py` (93) owns block construction and section detection (`_blocks_from_text_pages`, `_make_text_block`, `_renumber_blocks`, `_detect_section`, `_sections_from_blocks`, `_section_id`, `SECTION_SPLIT`); `cache.py` (117) owns cache I/O and fingerprinting (`_read_ocr_cache`, `_write_ocr_cache`, `_ocr_cache_path`, `_route_cache_engine_id`, `_active_ocr_cache_dimensions`, `_ocr_profile_options_fingerprint`, `_ocr_extractor_cache_fingerprint`, `_with_cache_status`, `_combined_cache_status`); `quality.py` (142) owns block annotation and per-page quality metrics plus the OCR debug metadata constants (`_annotate_ocr_blocks`, `_page_quality_from_blocks`, `_text_page_quality`, `_quality_band`, `_merge_ocr_debug_metadata`, `_ocr_unavailable_message`); `builder.py` (223) owns the public API and extraction orchestrator (`build_document_ir`, `file_sha256`, `_extract_blocks`, `_extract_pdf_blocks`, `_extract_pdf_ocr_pages`, `_extract_pdf_text_pages`, `_call_intelligent_ocr`). Dependency direction is acyclic (`blocks` and `cache` have no internal deps; `quality` is leaf; `builder` imports from all three; `__init__` imports from `builder` and `cache`). `_call_intelligent_ocr` and `_extract_pdf_blocks` look up `extract_with_intelligent_ocr` and `_extract_pdf_text_pages` via `app.services.ocr` at call time so existing test monkey-patches (`monkeypatch.setattr(ocr, "extract_with_intelligent_ocr", ...)` in `test_intelligent_ocr.py`, `test_core_business_optimization.py`, `test_next_step_optimization.py`) keep working without test changes; same trick on `_ocr_extractor_cache_fingerprint` so the fingerprint reflects the patched function. All 344 backend tests pass; rule baseline 0.9623 (153/159) reproduces byte-identically (`git diff` empty on the baseline JSON); frontend tests (9) and build pass; governance scan passes with no large-file warnings.
- Anchor: AGENTS.md 500-line soft trigger rule.

### done PLAN-split-evidence-first (2026-05-19)

- Goal: Reduce the 571-line `backend/app/services/evidence_first.py` (above the AGENTS.md 500-line soft trigger) to a focused subpackage where each module ≤ 400 lines.
- Outcome: Pure structural refactor, no behavior change. Replaced the monolithic file with `backend/app/services/evidence_first/`: `__init__.py` (10) re-exports the public API; `spans.py` (62) owns text-span utilities (`_negative_span`, `_positive_span`, `_section_complete_negative_span`, `_contains_uncertain`, `_trim_span`, `_match_group`, `_normalize_rule_value`) plus the `NEGATION_TERMS`/`UNCERTAIN_TERMS`/`SENTENCE_TERMINATORS` constants; `candidates.py` (94) owns `_candidate` builder, `_apply_forbidden_context`, `_is_family_context`, `_candidate_context_text`, `_source_type`, `_field_label_seen`, `_candidate_confidence`, `_dedupe_candidates`; `rules.py` (214) owns the 5 evidence collection functions including the behavior-critical `_binary_history_evidence` guards (skip `computed_from_facts`/`fact_then_code` and `discharge_group` fields); `collection.py` (33) owns the public `collect_local_evidence` entry point with a runtime lazy import of `_select_candidate` to avoid `collection ⇄ adjudication` cycle; `adjudication.py` (210) owns `adjudicate_field_decisions`, `decisions_to_extraction_candidates`, and their helpers (`_select_candidate`, `_priority_rank`, `_review_reasons`, `_generic_allowed`, `_decision_summary`, `_evidence_type`, `_candidate_facts`, `_missing_candidate`). All 344 backend tests pass; rule baseline 0.9623 (153/159) reproduces byte-identically (`git diff` empty on the baseline JSON); frontend tests (9) and build pass; governance scan passes with no large-file warnings.
- Anchor: AGENTS.md 500-line soft trigger rule.

### done PLAN-split-diagnostics (2026-05-19)

- Goal: Reduce the 633-line `backend/app/services/diagnostics.py` (above the AGENTS.md 500-line soft trigger) to a focused subpackage where each module ≤ 400 lines.
- Outcome: Pure structural refactor, no behavior change. Replaced the monolithic file with `backend/app/services/diagnostics/`: `__init__.py` (13) re-exports the public API (`build_case_diagnostics`, `quality_summary`, `frontend_evidence_config`, `processing_run`); `case_summary.py` (166) owns `build_case_diagnostics`, `_snapshot_model_calls`, `quality_summary`, `frontend_evidence_config`; `ocr_debug.py` (182) owns `_ocr_debug_summary` plus the fragmentation/duplicate/tile/table/low-quality check helpers and their geometry/text utilities (`_safe_int`, `_bbox_mid_y`, `_bbox_x1`, `_same_visual_line`, `_normalize_ocr_text`, `_recommended_ocr_debug_profiles`); `processing_run.py` (258) owns `processing_run`, `_run_record_payload`, `_step_timings`, the `_trace_*` family, and the `_model_call_payload` / `_event_payload` / `_vision_request_payload` builders that `case_summary` reuses; `ocr_availability.py` (56) owns the five `_extract_*` / `_default_ocr_unavailable_reason` helpers. `case_summary.py` imports payload builders from `processing_run.py` so the existing-runs branch keeps using shared payload shapes. `processing_run()` itself uses a function-local lazy import of `quality_summary` to keep module-level dependencies acyclic. All 344 backend tests pass; rule baseline 0.9623 (153/159) byte-identical; frontend tests (9) and build pass; governance scan passes with no large-file warnings on any new file.
- Anchor: AGENTS.md 500-line soft trigger rule.

### done PLAN-split-layout-normalizer (2026-05-19)

- Goal: Reduce the 767-line `backend/app/services/layout_normalizer.py` (above the AGENTS.md 500-line soft trigger) to a focused subpackage where each module ≤ 400 lines.
- Outcome: Pure structural refactor, no behavior change. Replaced the monolithic file with `backend/app/services/layout_normalizer/`: `__init__.py` (4) re-exports `normalize_document_layout` plus `LAYOUT_NORMALIZER_VERSION`; `sections.py` (44) owns `_detect_section`, `_standalone_key_label`, `_is_section_title_like`, `_compact_text`, `_section_id`, `_sections_from_blocks`, `_renumber_blocks`; `block_merging.py` (200) owns same-line and paragraph-wrap merging plus geometry helpers and `_is_screen_chrome` (kept here because `_can_merge_wrapped_paragraph` calls it directly); `classification.py` (118) owns `_classify_blocks`, `_split_patient_header_block_ids`, `_document_region`, `_region_rule_matches`, `_safe_search`, `_is_patient_header`, and the `LAYOUT_NORMALIZER_VERSION` constant; `key_value_derivation.py` (390) owns the full `_derive_*` family plus `_extract_key_values`, `_estimated_span_bbox`, table-cell helpers; `orchestrator.py` (61) owns the public `normalize_document_layout`. Dependency direction is acyclic (`sections` → `block_merging` → `classification`/`key_value_derivation` → `orchestrator`). All 344 backend tests pass; rule baseline 0.9623 (153/159) byte-identical; frontend tests (9) and build pass; governance scan passes with no large-file warnings on any new file.
- Anchor: AGENTS.md 500-line soft trigger rule.

### done PLAN-split-routes (2026-05-19)

- Goal: Reduce the 780-line `backend/app/api/routes.py` (above the AGENTS.md 500-line soft trigger) to a focused subpackage where each module ≤ 400 lines.
- Outcome: Pure structural refactor, no API contract change. Replaced the monolithic file with `backend/app/api/routes/`: `__init__.py` (32) re-exports the unified `router` plus the legacy `_pdf_source_render_scale` helper that `test_api_smoke.py` imports; `_helpers.py` (229) holds every private helper function; `health.py` (131) owns health/config/auth-status/field-dictionary; `models.py` (78) owns model profile and provider routes plus `ModelSelectionPayload` / `ActiveProviderModelPayload`; `cases.py` (188) owns the case CRUD plus `VisionFallbackRequestPayload`; `diagnostics.py` (23) owns `/cases/{case_id}/diagnostics`; `system.py` (197) owns project-config / system / runtime / maintenance routes; `evaluations.py` (74) owns the eval routes plus `BatchEvaluationCasePayload` / `BatchEvaluationPayload`. The governance scan was updated to walk the entire `backend/app/api/` tree for `@router.<method>(...)` decorators missing `response_model=` instead of hardcoding `routes.py`. Two tests that monkey-patched `app.api.routes.{enqueue_case, build_runtime_services}` now patch the actual sub-modules (`routes.cases`, `routes.system`). All 344 backend tests pass; rule baseline 0.9623 (153/159) unchanged; total `app.routes` count 40 unchanged; frontend tests (9) and build pass; governance scan passes with no large-file warnings.
- Anchor: AGENTS.md 500-line soft trigger rule.

## Older Done Entries

Rotated to `docs/PLAN_HISTORY.md` per AGENTS.md "Documentation Maintenance":

- 2026-05-29: E0-006 Split model_providers.py (2026-05-19).
- 2026-05-28: E0-004 Split llm_provider adapters and payloads (2026-05-19).
- 2026-05-27: PLAN-split-styles-css (2026-05-22).
- 2026-05-26: Decide application/ vs services/ flat layout (2026-05-19).
- 2026-05-25: PLAN-split-pipeline.py (2026-05-21).
- 2026-05-24: PLAN-mock-general-phase-B (tumor_history, E1-010, 2026-05-20).
- 2026-05-23: PLAN-llm-evidence-text-substring (E1-001 v3, 2026-05-19).
- 2026-05-22: E1-005 rule_pre_accepted shortcut (2026-05-18).
- 2026-05-19: PLAN-mock-general-phase-A (2026-05-18).
- 2026-05-21: PLAN-llm-provider-phase-3 (2026-05-18).
- 2026-05-20: E1-001 evidence-first prompt rewrite (2026-05-18).
- 2026-05-18: PLAN-llm-provider-phase-1; PLAN-llm-baseline-bootstrap; E1-005-synonym-widening; PLAN-field-coverage-and-ocr-postprocessing-research.
- 2026-05-17: PLAN-mock-general-challenge-case; PLAN-mock-general-coverage-expansion; E1-005-clause-boundary; PLAN-mock-general-baseline; E0-008 field-extraction eval runner; PLAN-write-architecture-doc; PLAN-write-roadmap; PLAN-write-reference-projects.
- 2026-04-30: ChartLens upgrade triage; dev branch workflow; OCR runtime engine override removal; CI and frontend test entrypoint.
