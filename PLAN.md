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

### done PLAN-split-frontend-types-api (2026-05-19)

- Goal: Reduce the 631-line `frontend/src/shared/types/api.ts` (above the AGENTS.md 500-line soft trigger) below the limit by splitting the 39 TypeScript interfaces into focused modules grouped by API surface concern, with each new file ≤ 350 lines.
- Outcome: Pure type-definition refactor with zero runtime impact (TypeScript type-only imports erase at build). Replaced the monolithic file with a 50-line barrel re-exporter `frontend/src/shared/types/api.ts` plus a sibling `frontend/src/shared/types/api/` subdirectory: `cases.ts` (271) owns `ReviewBand`, `EvidencePack`, `FieldResult`, `OcrBlock`, `OcrQuality`, `ProcessingRun`, `DocumentFragment`, `ModelCallLog`, `VisionFallbackRecord`, `CaseDiagnostics`, `CaseRecord`, `CaseSummary`, `DocumentIrResponse`, `SourceOcrResponse` (kept together because `OcrBlock.block_type` references `DocumentFragment["block_type"]`, `CaseRecord.results` references `FieldResult`, `CaseSummary.status` references `CaseRecord["status"]`, `CaseDiagnostics` references `OcrQuality`/`ProcessingRun`/`DocumentFragment`/`ModelCallLog`/`VisionFallbackRecord`, and `FieldResult.evidence_packs` references `EvidencePack`); `fields.ts` (89) owns `FieldDefinition`, `FieldDictionary`, `FieldGroupDefinition`, `EvidenceDisplayConfig`, `ProjectConfig`; `auth.ts` (43) owns `AuthStatus`; `models.ts` (123) owns `ModelProfile`, `ModelProfilesResponse`, `ModelProfileSelectionResponse`, `ProviderModel`, `ModelProviderSelection`, `ModelProvider`, `ModelProvidersResponse`, `ModelProviderUpdatePayload`, `ModelProviderUpdateResponse`, `ModelProviderFetchResponse`, `ModelProviderActivationResponse`; `system.ts` (106) owns `SystemSettingsResponse`, `FieldDictionarySettingsResponse`, `RuntimeSettingsResponse`, `RuntimeServices`, `RuntimeServiceStatus`, `RuntimeServiceCheck`, `RuntimeServiceAction`, `SettingsValidationPayload`, `SettingsValidationResponse`, `MaintenanceResult`. The single cross-file type reference (`FieldDictionarySettingsResponse.field_dictionary.fields: FieldDefinition[]`) lands as `import type { FieldDefinition } from "./fields";` in `system.ts`; all other modules are dependency-free. The barrel preserves the canonical `frontend/src/shared/types/api` import path so all 24 consumer sites (e.g. `SettingsPanel.tsx`, `ProviderSettingsPanel.tsx`, `EvidencePanel.tsx`, `DiagnosticsPage.tsx`, `useChartLensState.ts`, `caseSwitching.ts`, plus 4 tests) keep working with their existing `import type { ... } from "../../shared/types/api"` statements unchanged. Frontend tests (9) pass; `npm run build` succeeds with the same `SettingsPanel-*.js` chunk layout; governance scan passes with no large-file warnings on any of the six files (50 / 271 / 89 / 43 / 123 / 106).
- Anchor: AGENTS.md 500-line soft trigger rule.

### done PLAN-split-provider-settings-panel (2026-05-19)

- Goal: Reduce the 614-line `frontend/src/features/settings/ProviderSettingsPanel.tsx` (above the AGENTS.md 500-line soft trigger) below the limit by extracting pure utility/formatter functions into a sibling module, with each new file ≤ 400 lines.
- Outcome: Pure structural refactor, no behavior change. Moved every pure helper out of `ProviderSettingsPanel.tsx` (614 → 482 lines) into a new sibling `frontend/src/features/settings/providerHelpers.tsx` (156 lines): `providerIcon`, `modelSettingsPayload`, `providerApiOptions`, `providerOptionSchema`, `modelOptionsHelp`, `reasoningEffortLabel`, `formatProviderTime`, `providerHasCredential`, `providerHasBaseUrl`, `providerIsRunnable`, `providerBlockingText`, `credentialStatusText`, `providerStatusText`, `providerTone`, `connectionStatusText`, `modelCountText`, `apiTypeLabel`, `modelSource`, `groupModelsBySource`, `modelSourceLabel`, `modelSourceHelp`, `modelSourceBadge`, `modelForUpdate`, plus the local `DraftState`, `ModelSource`, `ProviderOptionSchema` type aliases, the `MODEL_SOURCE_ORDER` array, and the `OPENAI_CHAT_OPTION_SCHEMA` constant. The helpers file uses the `.tsx` extension because `providerIcon` returns JSX (`<Bot/>`/`<Zap/>`/`<Cloud/>`/`<Server/>`/`<KeyRound/>` from `lucide-react`); a `.ts` file cannot host the JSX literals. The component now imports those helpers as named values plus `import type { DraftState }` (preserving `import type` discipline) and trims its `lucide-react` import set to only the icons it still renders directly (`AlertTriangle`, `CheckCircle2`, `Plus`, `RefreshCw`, `Search`); icon imports used only by the moved `providerIcon` helper (`Bot`, `Cloud`, `KeyRound`, `Server`, `Zap`) live in `providerHelpers.tsx`. The `ModelProvider` type import was dropped from the panel since the component no longer references it directly. Both `useMemo` callsites (`groupModelsBySource(models)` and the `models` filter) keep working because the helpers are pure imports. Frontend tests (9) pass; `npm run build` succeeds with the same `SettingsPanel-*.js` chunk layout; governance scan passes with no large-file warnings on either file (482 / 156). Component still named-exports `ProviderSettingsPanel` exactly as before.
- Anchor: AGENTS.md 500-line soft trigger rule.

### done PLAN-split-chartlens-app (2026-05-19)

- Goal: Reduce the 703-line `frontend/src/features/app/ChartLensApp.tsx` (above the AGENTS.md 500-line soft trigger) to a focused module set where each file ≤ 500 lines, with no visual or functional change.
- Outcome: Pure structural refactor, no behavior change. Lifted every state hook, ref, derived `useMemo`, every `useEffect` (bootstrap, route sync, diagnostics-on-case-switch, selectedField rebinding, reviewCode rebinding) and every async handler (`refreshAuthStatus`, `bootstrap`, `loadRuntimeSettings`, `loadProjectConfig`, `loadFieldDictionary`, `refresh`, `loadDiagnostics`, `onUpload`, `submitReprocess`, `approveVisionFallback`, `submitExport`, `submitReview`, `removeCase`, `clearLocalCases`) into a single custom hook `frontend/src/features/app/useChartLensState.ts` (486 lines). The hook returns one flat object so `ChartLensApp.tsx` (336 lines) destructures it and stays render-only; `ChartLensState` is exposed as `ReturnType<typeof useChartLensState>` so the JSX consumer keeps full type safety without a hand-maintained interface mirror. Moved the two small fallback components (`SettingsPanelFallback`, `CaseDetailLoading`) to `frontend/src/features/app/components.tsx` (20 lines). Moved `mergeCaseRecord` next to its existing peers in `frontend/src/features/app/caseSwitching.ts` (25 lines, was 18) since it composes with the same `CaseRecord` shape; the existing `caseSwitching.test.ts` keeps passing because no exported symbol is removed. The `useCasePolling({ refresh, loadDiagnostics })` wiring stays unchanged so the hook's polling behavior, the `diagnosticsRequestSeq` race guard, the `Suspense` boundary around the lazy `SettingsPanel`, and the empty-state JSX paths are byte-equivalent. Frontend tests (9) pass; `npm run build` succeeds with the same bundle layout (`SettingsPanel-*.js` chunk preserved); governance scan passes with no large-file warnings on any of the four files (336 / 486 / 25 / 20).
- Anchor: AGENTS.md 500-line soft trigger rule.

### done PLAN-split-ocr (2026-05-19)

- Goal: Reduce the 532-line `backend/app/services/ocr.py` (above the AGENTS.md 500-line soft trigger) to a focused subpackage where each module ≤ 300 lines.
- Outcome: Pure structural refactor, no behavior change. Replaced the monolithic file with `backend/app/services/ocr/`: `__init__.py` (13) re-exports the public API (`build_document_ir`, `file_sha256`) plus the test-monkeypatch surface (`extract_with_intelligent_ocr`, `_extract_pdf_text_pages`, `_ocr_cache_path`, `_ocr_extractor_cache_fingerprint`, `_extract_blocks`, `_extract_pdf_blocks`, `_extract_pdf_ocr_pages`, `_call_intelligent_ocr`); `blocks.py` (93) owns block construction and section detection (`_blocks_from_text_pages`, `_make_text_block`, `_renumber_blocks`, `_detect_section`, `_sections_from_blocks`, `_section_id`, `SECTION_SPLIT`); `cache.py` (117) owns cache I/O and fingerprinting (`_read_ocr_cache`, `_write_ocr_cache`, `_ocr_cache_path`, `_route_cache_engine_id`, `_active_ocr_cache_dimensions`, `_ocr_profile_options_fingerprint`, `_ocr_extractor_cache_fingerprint`, `_with_cache_status`, `_combined_cache_status`); `quality.py` (142) owns block annotation and per-page quality metrics plus the OCR debug metadata constants (`_annotate_ocr_blocks`, `_page_quality_from_blocks`, `_text_page_quality`, `_quality_band`, `_merge_ocr_debug_metadata`, `_ocr_unavailable_message`); `builder.py` (223) owns the public API and extraction orchestrator (`build_document_ir`, `file_sha256`, `_extract_blocks`, `_extract_pdf_blocks`, `_extract_pdf_ocr_pages`, `_extract_pdf_text_pages`, `_call_intelligent_ocr`). Dependency direction is acyclic (`blocks` and `cache` have no internal deps; `quality` is leaf; `builder` imports from all three; `__init__` imports from `builder` and `cache`). `_call_intelligent_ocr` and `_extract_pdf_blocks` look up `extract_with_intelligent_ocr` and `_extract_pdf_text_pages` via `app.services.ocr` at call time so existing test monkey-patches (`monkeypatch.setattr(ocr, "extract_with_intelligent_ocr", ...)` in `test_intelligent_ocr.py`, `test_core_business_optimization.py`, `test_next_step_optimization.py`) keep working without test changes; same trick on `_ocr_extractor_cache_fingerprint` so the fingerprint reflects the patched function. All 344 backend tests pass; rule baseline 0.9623 (153/159) reproduces byte-identically (`git diff` empty on the baseline JSON); frontend tests (9) and build pass; governance scan passes with no large-file warnings.
- Anchor: AGENTS.md 500-line soft trigger rule.

### done PLAN-split-evidence-first (2026-05-19)

- Goal: Reduce the 571-line `backend/app/services/evidence_first.py` (above the AGENTS.md 500-line soft trigger) to a focused subpackage where each module ≤ 400 lines.
- Outcome: Pure structural refactor, no behavior change. Replaced the monolithic file with `backend/app/services/evidence_first/`: `__init__.py` (10) re-exports the public API; `spans.py` (62) owns text-span utilities (`_negative_span`, `_positive_span`, `_section_complete_negative_span`, `_contains_uncertain`, `_trim_span`, `_match_group`, `_normalize_rule_value`) plus the `NEGATION_TERMS`/`UNCERTAIN_TERMS`/`SENTENCE_TERMINATORS` constants; `candidates.py` (94) owns `_candidate` builder, `_apply_forbidden_context`, `_is_family_context`, `_candidate_context_text`, `_source_type`, `_field_label_seen`, `_candidate_confidence`, `_dedupe_candidates`; `rules.py` (214) owns the 5 evidence collection functions including the behavior-critical `_binary_history_evidence` guards (skip `computed_from_facts`/`fact_then_code` and `discharge_group` fields); `collection.py` (33) owns the public `collect_local_evidence` entry point with a runtime lazy import of `_select_candidate` to avoid `collection ⇄ adjudication` cycle; `adjudication.py` (210) owns `adjudicate_field_decisions`, `decisions_to_extraction_candidates`, and their helpers (`_select_candidate`, `_priority_rank`, `_review_reasons`, `_generic_allowed`, `_decision_summary`, `_evidence_type`, `_candidate_facts`, `_missing_candidate`). All 344 backend tests pass; rule baseline 0.9623 (153/159) reproduces byte-identically (`git diff` empty on the baseline JSON); frontend tests (9) and build pass; governance scan passes with no large-file warnings.
- Anchor: AGENTS.md 500-line soft trigger rule.

## Older Done Entries

Rotated to `docs/PLAN_HISTORY.md` per AGENTS.md "Documentation Maintenance":

- 2026-06-01: PLAN-split-diagnostics (2026-05-19).
- 2026-05-31: PLAN-split-layout-normalizer (2026-05-19).
- 2026-05-30: PLAN-split-routes (2026-05-19).
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
