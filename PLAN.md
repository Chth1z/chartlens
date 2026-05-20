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

### done Prune dead schema fields in domain/models.py (2026-05-20)

- Goal: Identify and remove fields on `ExtractionCandidate`, `EvidencePack`, `EvidenceCandidate`, and `DocumentIRBlock` that have no read site in `services/` or `frontend/`.
- Outcome: Comprehensive search confirmed all initial suspects (`candidate_id`, `candidate_group_id`, `canonical_source_ids`, `layout_region_id`, `line_group_id`, `evidence_packs`, `evidence_candidates`) have active read sites in OCR engine pipeline (`canonicalize.py`, `engine_base.py`, `source_ocr.py`), frontend TypeScript types (`cases.ts`), and UI components (`ReviewPanel.tsx`, `evidenceText.ts`). No dead fields found; no changes needed. Quarterly checkpoint satisfied.
- Done condition: Every Pydantic field confirmed to have at least one explicit read site outside `domain/models.py`.

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

### todo M1-002 Async LLM provider HTTP I/O (deferred)

- Deferred reason: Pure adapter async-only migration without pipeline restructure adds maintenance cost without observable runtime benefit. Current evidence-first mode does one LLM call per case for all fields together.
- Trigger: when E2-003 throughput baseline shows LLM-call wait time dominates.
## Done

The five most recent done entries stay here in detail. Older done entries live in `docs/PLAN_HISTORY.md` (rotation rule: AGENTS.md "Documentation Maintenance"). When a new done entry lands, the oldest entry in this section moves to `docs/PLAN_HISTORY.md` as a one-paragraph summary plus a link to its DECISIONS anchor when one exists.

### done M1-003 Dependency lockfile + supply-chain audit (2026-05-19)

- Goal: Add supply-chain security scanning to CI: `pip-audit` (vulnerability scan), `bandit` (SAST), `npm audit` (frontend advisories). Upgrade vulnerable deps (`python-multipart` 0.0.20 → 0.0.29, `pypdf` 6.4.1 → 6.11.0) to pass the audit clean.
- Outcome: New CI job `security` (ubuntu-latest, parallel with backend/frontend) runs pip-audit against `requirements.txt`, bandit against `backend/app/` with a config file, and `npm audit --audit-level=high` against frontend. Created `backend/requirements-audit.txt` (CI-only audit deps: pip-audit 2.9.0, bandit 1.9.4) and `backend/bandit.yaml` (false-positive skips for B101/B105/B110/B112/B311/B324/B404/B603/B607). Upgraded `python-multipart` (3 CVEs fixed) and `pypdf` (18 CVEs fixed) in `requirements.txt`. All 359 backend tests pass with upgraded deps; pip-audit exits 0; bandit exits 0; npm audit exits 0; 9 frontend tests pass; governance scan clean.
- Anchor: `docs/MODERNIZATION_PLAN.md` M1-003.

### done M1-002 In-process FTS index reuse per case (2026-05-19)

- Goal: Build the SQLite FTS5 evidence-search index once per case and reuse it across every `build_evidence_packs` / `evidence_for_field` call in that case. Replace the per-field `sqlite3.connect(":memory:")` + `CREATE VIRTUAL TABLE` + bulk insert cycle (mock_general baseline = 22 fields × 19 cases = 418 builds per run) with one build per case.
- Outcome: Pure perf refactor, behavior byte-equivalent. New `EvidenceIndex` dataclass plus `build_evidence_index()` constructor and `evidence_index()` context manager in `backend/app/services/evidence.py` (file 280 → 445 lines, still under the 500-line soft trigger). Threaded an optional `index: EvidenceIndex | None = None` parameter through `evidence_for_field`, `build_evidence_packs`, `_field_evidence_pack_payload`, `_llm_user_payload`. `_fts_scores` was split into `_fts_scores_with_index(index, terms)` (uses the existing connection) and a thin `_fts_scores(blocks, terms)` wrapper that builds a temporary index for ad-hoc callers (`compact_group_context`, tests). Both `pipeline_evidence_first._extract_document_evidence_first` and `pipeline.extract_document` (legacy `group_evidence_pack` path) now call `build_evidence_index(document_ir.blocks)` once per case and pass `index=case_index` to every downstream call, wrapped in `try/finally` so the in-memory sqlite connection is always closed. New contract test file `backend/tests/test_evidence_index.py` (4 tests, 0.38s): indexed packs identical to legacy packs across 6 schema fields (gender, age, hypertension_history, diabetes_history, smoking_history, drinking_history) — comparing pack_hash, score, match_terms, score_reason, neighbor_block_ids, negated/uncertain/family_context flags; `close()` is idempotent (double-close is a no-op); `block_ids_signature` differs when block order differs (so a future stale-index check has a cheap comparator); the context manager closes on exit. Verification: 359 backend tests pass (was 355 + 4 new); rule baseline `mock_general.json` byte-equivalent (`git diff` empty after regeneration); 9 frontend tests + build clean; governance scan clean. Perf measurement: end-to-end eval test wall clock dropped 5% (7.30s → ~6.91s mean of 3 runs); a focused `build_evidence_packs` micro-benchmark (19 cases × 23 fields × 60 blocks) shows 2.24× speedup (0.516s → 0.231s, 55% reduction) — the targeted improvement is fully realized in the FTS code path; the eval test is dominated by OCR/dedup/SQLAlchemy round-trips. Residual: `compact_group_context()` (no production caller) and the LLM `_llm_cache_key` path still build their own FTS index per call; both are negligible and out of scope for this task.
- Anchor: `docs/MODERNIZATION_PLAN.md` M1-005 (re-numbered as M1-002 in the rolling plan).

### done M1-001 Provider-capability-aware structured output routing (2026-05-19)

- Goal: Add `structured_output_mode` to `ModelProfile` (values: `json_schema` strict / `json_object` / `tools` / `text`). The OpenAI-compatible adapter picks the strongest mode the active profile declares, falls back on a 400-class capability error to the next mode, and records the downgrade in `last_usage.structured_output_mode` and `last_usage.structured_output_downgrade`. Default values per profile: `openai_structured` → `json_schema`, `deepseek_v4_flash` / `deepseek_v4_pro` → `json_schema` (DeepSeek V3.2+ supports strict `response_format={"type":"json_schema",...}`), `openrouter_auto` / `ollama_local` / `openai_compatible_custom` → `json_object`, `local_disabled` → `text`. The existing v3.x prompt rules (contiguous-substring, placeholder-not-value) stay in place; this task added the schema-enforcement layer underneath them, not replacing them.
- Outcome: Pure capability-routing change, no behavior regression. Modified files (10): `backend/app/domain/models.py` adds `structured_output_mode: Literal["json_schema","json_object","tools","text"] = "json_object"` next to the existing `response_format` field; `backend/app/services/llm_provider/payloads.py` introduces `STRUCTURED_OUTPUT_MODE_ORDER` and `_chat_response_format_for_mode(mode, schema, schema_name)` helper, and threads `structured_output_mode` through `_chat_completions_payload`; `backend/app/services/llm_provider/payloads_evidence_first.py:_chat_completions_evidence_first_payload` now reads the mode from the active profile (override-able per-call), drops the schema descriptor from the system prompt suffix when mode == json_schema (the API enforces it), and keeps the descriptor when mode == json_object; `backend/app/services/llm_provider/cache.py` includes `structured_output_mode` in both `_llm_cache_key` and `_evidence_first_cache_key` so flipping the mode invalidates cached results; `backend/app/services/llm_provider/adapters/openai_compatible.py` adds `_run_chat_request` that shares the api_key + base_url retry matrix between `extract_group` and `collect_evidence`, plus `_StructuredOutputCapabilityError` + `_is_structured_output_capability_error` matcher (status 400 + capability marker keywords) + `_CHAT_DOWNGRADE_NEXT` ladder (json_schema → json_object → text); both `extract_group` and `collect_evidence` now build the payload per mode and rebuild + retry once on capability error, recording the downgrade reason; `backend/tests/test_provider_phase_3.py` updated so the contract test follows the new `_run_chat_request` indirection (still asserts `client.chat.completions.create` happens, just on the helper). Each of the 7 `config/model_profiles/*.yaml` declares an explicit `structured_output_mode` matching the mapping above. New contract test file `backend/tests/test_provider_structured_output.py` (+11 tests, 0.59s) asserts: every YAML declares the mode in the allowed set; `_chat_response_format_for_mode` emits strict json_schema with `strict: true` and the right schema name; the helper rejects `tools` / `text` / `garbage` with ValueError; the json_schema payload drops the embedded schema descriptor from the system prompt while keeping the business-rule prose (`evidence_text 必须为引用 block 的连续子串`); the json_object payload keeps the schema descriptor in the system prompt; `extract_group` payload emits strict json_schema when the profile declares it; the capability downgrade runs end-to-end against a stubbed `OpenAI` client that raises a 400 capability error on the first call and returns a valid evidence response on the second call (asserts the second `response_format` is `{"type":"json_object"}` and `last_usage["structured_output_mode"] == "json_object"` and `last_usage["structured_output_downgrade"]` is a non-empty `json_schema -> json_object: ...` string); the cache key flips when the mode flips so a downgraded run cannot read back a stricter-mode cache entry. Verification: 355 backend tests pass (was 344 + 11 new); 9 frontend tests pass; `npm run build` succeeds with same chunk layout (`SettingsPanel-*.js`); governance scan clean; rule baseline `mock_general.json` 153/159 byte-equivalent (`git diff` empty); LLM baseline rerun deferred to next session that has API access.
- Anchor: `docs/MODERNIZATION_PLAN.md` M1-001; AGENTS.md Precision Tasks rule (this is structural, not a precision change, so the LLM baseline stays at the committed 159/159 until the next prompt revision exercises strict json_schema in production).



## Older Done Entries

Rotated to `docs/PLAN_HISTORY.md` per AGENTS.md "Documentation Maintenance":

- 2026-05-20: PLAN-split-frontend-types-api (2026-05-19).
- 2026-05-20: PLAN-split-provider-settings-panel (2026-05-19).
- 2026-06-04: PLAN-split-chartlens-app (2026-05-19).
- 2026-06-03: PLAN-split-ocr (2026-05-19).
- 2026-06-02: PLAN-split-evidence-first (2026-05-19).
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
