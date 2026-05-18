# EYEX Repository Rules

This file is the project constitution for personal Codex-assisted development. Keep it short, concrete, and stricter than memory. Rules describe the current state of the repository, not aspirations; aspirational items go in `PLAN.md` or `docs/ROADMAP.md`.

## Documentation Map

Treat these files as the canonical layers. Read them in this order when starting an unfamiliar task.

Constitutional layer:

- `AGENTS.md` (this file): project constitution and rule source. Edit only when the rule is meant to be enforced today.
- `PLAN.md`: lightweight personal task board. Each item has goal, out-of-scope, acceptance commands, risk, trigger, done condition, and a stable task ID. Holds the work that is ready to start.
- `docs/PLAN_HISTORY.md`: older `PLAN.md` Done entries rotated out per the rules in "Documentation Maintenance".
- `docs/DECISIONS.md`: short, dated decision log for high-impact architecture, data, security, OCR, LLM, or workflow choices. Carries an "Active Index" header listing every active entry; superseded and archived entries stay in the file with the matching `Status:` line.
- `docs/archive/`: read-only history. Older subsystem notes (OCR, LLM provider) live here once superseded. Each archived file points back to the active doc that replaced it.

User-facing and orientation layer:

- `README.md`: how to install, configure, and run EYEX. User-facing only; architecture detail belongs elsewhere.
- `docs/CODEX_WORKFLOW.md`: per-session checklist and prompt template for Codex sessions.

Architecture and roadmap layer:

- `docs/ARCHITECTURE.md`: single source of truth for the main pipeline, layering, module responsibilities, and boundary contracts (DocumentIR, DocumentContext, EvidenceCandidate, FieldDecision, ExtractionCandidate, ValidatedFieldResult).
- `docs/ROADMAP.md`: phased optimization plan with task IDs (`E0-NNN` / `E1-NNN` / `E2-NNN`). Each roadmap task has an eval-profile-anchored acceptance line and a list of prerequisite IDs.
- `docs/API_BOUNDARY.md`: backend/frontend API contract rules.
- `docs/FIELD_COVERAGE.md`: inventory of every export-template field, current `mock_general` baseline coverage, and the phased fixture-expansion plan that walks `mock_general` from demographics and history to the full export sheet.

Reference and subsystem layer:

- `docs/REFERENCE_PROJECTS.md`: open-source projects EYEX borrows ideas from, with commit-pinned URLs, license verification, and an explicit non-copy boundary per entry.
- `THIRD_PARTY_NOTICES.md`: required attribution ledger for any source-level reuse. Currently records that EYEX does not vendor source from agent frameworks; updated on each adapter-vendor commit.
- `docs/LLM_PROVIDER_REFACTOR.md`: deep analysis and three-phase plan behind ROADMAP `E1-011` (default-inheritance shim that silently routed DeepSeek / Anthropic / Gemini / OpenRouter to rule extraction). All three phases are now done; keep the doc as the historical rationale for the explicit-delegation rule below.
- `docs/LLM_PROVIDER_ALIGNMENT.md`: 2026-04-30 status note on aligning EYEX's LLM provider layer with OpenClaw / Cline / Continue / LiteLLM patterns. Older than `LLM_PROVIDER_REFACTOR.md`; defer to the refactor doc and to `docs/DECISIONS.md` when the two disagree.
- `docs/OCR_UPGRADE.md`: current OCR runtime route (PP-StructureV3 plus PP-OCRv5 server ONNX on DirectML) and the reasons PaddleOCR-VL is parked outside it. Defer to `docs/DECISIONS.md` when entries disagree.
- `docs/OCR_POST_PROCESSING.md`: research notes on character correction, medical entity normalization, table structure recovery, and reading order in Chinese clinical OCR. Reference research only; nothing here is a runtime dependency yet.

Conflict resolution:

- When `docs/ARCHITECTURE.md` and a `docs/DECISIONS.md` entry disagree, the decision wins and the architecture doc is updated to match.
- When `PLAN.md` and `docs/ROADMAP.md` disagree on the same task, `PLAN.md` is the one being executed.
- When `docs/LLM_PROVIDER_REFACTOR.md` and `docs/LLM_PROVIDER_ALIGNMENT.md` disagree, the refactor doc wins.
- When `docs/OCR_UPGRADE.md` describes a route that contradicts the active `config/ocr_profiles/*.yaml`, the active YAML is authoritative for runtime; update `docs/OCR_UPGRADE.md` in the same change.

## Personal Codex Workflow

- One session has one primary goal. Do not mix feature work, refactor, UI polish, and infrastructure cleanup in the same pass unless the user explicitly asks for a combined change.
- Start every non-trivial task by reading this file, inspecting the relevant files, and checking `git status --short`. Do not work from memory.
- For work likely to exceed 30 minutes or touch multiple subsystems, write a short plan before editing. Small focused fixes may be implemented directly.
- Prefer test-first or verification-first changes for behavior work: write or adjust the failing test/check, confirm it fails, then change implementation.
- Remove old logic, routes, fields, and environment variables by default. Do not add compatibility layers unless a real external dependency exists; if compatibility is kept, document its deletion condition.
- If unrelated dirty files exist, leave them alone. If they affect the task, explain the conflict before changing the affected area.
- Single-file complexity ceilings:
  - Soft trigger at 500 lines for any backend `*.py`, frontend `*.ts` / `*.tsx`, or stylesheet `*.css`. The next task touching that file must include a split. The pre-split task must still pass full quality gates.
  - Hard governance warning at 800 lines, surfaced by `scripts\project-governance-check.ps1`. Crossing it without a follow-up split task in `PLAN.md` is a violation.
- Major architecture direction changes (introducing or removing `application/`, reshaping `services/` subpackages, swapping the primary data flow, changing OCR/LLM routing fundamentals) must be recorded in `docs/DECISIONS.md` before code lands.
- After any approach has failed twice, stop incremental patching and write a one-line root-cause hypothesis before the third attempt.

## Personal GitHub Management

- Treat `main` as the stable upstream branch and `dev` as the personal integration branch where every change lands first.
- Default integration target for any new commit is `dev`. Routine work commits directly to `dev` after passing local quality gates; do not open a `codex/<goal>` branch unless the work has a real reason to be isolated (uncertain blast radius, parallel exploration, large refactor with intermediate broken states).
- `main` is updated only when `dev` has accumulated enough finished change and is stable. Promotion requires all of: a clean full quality-gate pass on `dev`, a clean governance scan, an intentional review of the diff, and a one-paragraph promotion note recorded in the merge commit message. Never push directly to `main`.
- When a `codex/<goal>` branch is genuinely needed, branch it from `dev`, finish the task, run the task-specific verification, and fast-forward merge it back into `dev` (delete the branch immediately after merge). One task branch represents one primary goal.
- PRs are optional for this single-developer setup. When a PR is opened (typically for high-risk or cross-module changes), keep it draft until backend tests, frontend tests, frontend build, and the governance scan all pass. When no PR is opened, the same fields belong in the commit message footer or `PLAN.md` Done section.
- Never stage `.env`, runtime state, model downloads, caches, generated test output, frontend build artifacts, or anything inside `references/`. Runtime data belongs in ignored directories such as `var/`, `storage/`, `logs/`, `output/`, and `tmp/`.
- Every pushed branch (including `dev`) must have a completion or promotion note covering changed behavior, validation commands, intentionally skipped areas, and residual risks.
- High-impact decisions for API contracts, OCR/LLM routing, evidence integrity, storage, security, or GitHub workflow must be recorded in `docs/DECISIONS.md` before or with the branch.
- Long-running branches that accumulate more than 60 dirty files must stop new feature work until the dirty set is merged, split, or discarded. Mixing in fresh refactors on top of that state is forbidden.
- Each `codex/<goal>` branch has a 2-week life cap. If it is still open after that, write the cause in `PLAN.md` and either close it or split it; do not silently let task branches age.

## Commit Traceability

Every commit must be traceable to an explicit task. Use this message format:

```text
<type>: <subject up to 70 chars>

<optional body, wrapped at ~80 chars>

Refs: <task-id>[, <task-id>...]
Verification: <exact commands actually run>
```

Rules:

- `<type>` is one of `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `chore`, `ci`.
- `<task-id>` formats:
  - `PLAN-<short-slug>` for items currently in `PLAN.md` (the slug is the kebab-cased title).
  - `E0-NNN` / `E1-NNN` / `E2-NNN` for items in `docs/ROADMAP.md`.
  - `governance-foundation`, `release-promotion`, or another stable kebab-case label for one-off cross-cutting work that does not yet have a PLAN entry. Such labels must be unique and short-lived; if they recur, promote them to a PLAN task.
- `Verification:` lists the commands actually executed. Use `none (docs only)` for pure documentation commits and skip the line for that case only.
- Promotion merges (`dev` to `main`) include a one-paragraph promotion note in the merge commit body in addition to the standard footer.
- Squash or amend only your own unpushed commits. Never rewrite shared history on `dev` or `main`.

## Codex Task Template

Use this template when asking Codex to make a change:

```text
Goal:
Do not change:
Old logic policy: delete / keep until <condition>
Required verification:
Completion report: changed files + validation results + risks + next best step
```

## Directory Boundaries

- `config/` contains versioned clinical, extraction, export, validation, OCR, and model profile configuration. Domain behavior changes happen here first.
- `backend/app/` contains application code only. Do not put editable project configuration back under `backend/app/data`.
- `var/` is runtime state: SQLite databases, uploads, OCR cache, provider settings, local secrets, downloaded models, and other generated artifacts. It is ignored.
- `storage/`, `logs/`, `output/`, and `tmp/` are previous or temporary runtime locations and remain ignored.
- `references/` is reserved for shallow local clones of upstream open-source projects used for read-only study. It is ignored. Never import code from this directory into `backend/` or `frontend/`; copy with attribution into a clearly named adapter directory if reuse is required (see Reference Projects Policy).
- `frontend/src/shared/api/client.ts` is the canonical frontend API client. Do not reintroduce parallel clients under `frontend/src/lib`.
- `docs/archive/` holds rotated content (older OCR decisions, retired phase plans). Files placed here are read-only history; do not edit them in place. Add a top-of-file pointer to the active doc that supersedes them.
- `docs/PLAN_HISTORY.md` holds older `PLAN.md` Done entries after the rotation in Documentation Maintenance.

## Architecture Boundaries

- Keep API routers thin: request validation, HTTP status mapping, and response assembly only.
- Frontend-facing backend endpoints must declare an explicit `response_model`; OpenAPI is the API contract source for the frontend boundary.
- Frontend API calls must go through `frontend/src/shared/api/client.ts`, normalize FastAPI errors as `ApiError`, and avoid direct ad hoc `fetch` calls.
- Domain behavior is config-driven. Domain rules, prompts, section aliases, redaction patterns, and document-kind mapping live in `config/document_profiles/*.yaml` and are read through `services/domain_profile.py` plus `services/layout_normalizer.py`. Do not reintroduce a runtime plugin registry such as `domain_plugins.register_domain_plugin`; the governance scan flags those identifiers.
- Keep model provider protocol adapters separate from clinical extraction rules.
- Keep OCR routing controlled by `config/ocr_profiles/*.yaml`; do not add runtime engine override environment variables.
- Non-`unknown` extraction results must keep evidence spans grounded in the de-identified `DocumentIR`.
- Config is product behavior. Changes under `config/` require config contract tests.
- Do not introduce abstractions just to hide old behavior. Add an abstraction only when it reduces real duplication or isolates a stable boundary.
- LLM calls must go through the LLM provider router (currently `backend/app/services/llm_provider/`). Business pipelines must not import a specific protocol adapter directly; routing, fallback, and key cooldown policy belong to the router layer.
- Every concrete `SemanticExtractionProvider` subclass must define `collect_evidence` and `extract_group` directly on itself. Inheriting the base-class default is forbidden because the base class declares both as `@abstractmethod`. An adapter that intentionally delegates the LLM call to the rule path must do so explicitly by returning `local_collect_evidence_fallback(document_context, fields)` and assigning `local_evidence_fallback_usage()` to `self.last_usage`. The contract is enforced by `backend/tests/test_provider_contracts.py`. See `docs/LLM_PROVIDER_REFACTOR.md` and `docs/DECISIONS.md` 2026-05-18 for the rationale.
- The `evidence_first_multimodal` extraction strategy may bypass the LLM router entirely for fields whose group declares `semantic_strategy: rule_shortcut` AND whose `rule_shortcut_extract` returns a candidate at confidence >= 0.95. Bypassed candidates carry `acceptance_reason="rule_pre_accepted"`, `provenance.source="rule_shortcut"`, `provenance.skipped_llm=True`, and `provenance.decision_status="PASS"`. The shortcut is asserted by `test_rule_shortcut_high_confidence_skips_llm_collect_evidence` in `backend/tests/test_evidence_first_extraction.py`; do not silently re-route shortcut-eligible fields back through the LLM. See `docs/DECISIONS.md` 2026-05-18 for the rationale.
- Target boundary for OCR layering: `backend/app/services/ocr_engine/` produces raw and single-engine canonical output only; profile-driven same-line merging, paragraph reflow, screen-chrome removal, patient-header detection, and key-value derivation belong to `backend/app/services/layout_normalizer.py`. Existing `canonicalize.py` overlap is tracked in `PLAN.md` as a split task; new code must not add to the overlap.
- Any change to `processing_runs`, `processing_events`, or `model_calls` schema is an observability contract change and must be recorded in `docs/DECISIONS.md`.
- `ExtractionCandidate`, `EvidencePack`, `EvidenceCandidate`, and `DocumentIRBlock` go through a quarterly dead-field prune: any Pydantic field with no read site in `services/` or `frontend/` must be removed.

## Reference Projects Policy

- Default mode is reference-only. When borrowing a design, algorithm, or data structure from an open-source project, document it in `docs/REFERENCE_PROJECTS.md` with a commit-pinned URL (`github.com/<org>/<repo>/blob/<sha>/<path>`), the upstream license, and the EYEX file or design that incorporates the idea. Do not commit upstream source.
- Local study clones go under `references/` (gitignored), preferably as `--depth=1`. Treat them as read-only research material; do not symlink, package, or import from this directory in production code.
- Source-level reuse is allowed only when there is no idiomatic alternative. Place copied code in a clearly named adapter directory (for example `backend/app/services/llm_provider/<vendor>/`), preserve the upstream `LICENSE` and `NOTICE`, retain copyright headers, and add an entry to `THIRD_PARTY_NOTICES.md` describing scope, version pinned, and local modifications.
- License compatibility check is mandatory before any source copy. MIT, Apache-2.0, and BSD are accepted; GPL, AGPL, OWUI-style brand-restricted, and Dify-modified-Apache require explicit decision in `docs/DECISIONS.md` before code lands.
- License re-verification cadence: every 90 days, or before any source-level reuse. Each entry in `docs/REFERENCE_PROJECTS.md` carries a `Verified:` date; update it during the quarterly sweep (see Documentation Maintenance).

## Quality Gates

- Backend: `python -m pytest backend\tests`
- Frontend tests: `cd frontend; npm test`
- Frontend build: `cd frontend; npm run build`
- Governance scan after cleanup, refactor, or rule-touching work: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`
- High-risk LLM/OCR/evidence changes also need an eval profile run or a documented reason why no eval data applies (see Precision Tasks).

## Dependency Management

- Backend `requirements*.txt` must pin exact versions. New dependencies must be checked for upstream activity (one update in the last year), license compatibility for personal use, and absence of known supply-chain incidents.
- Frontend dependencies are locked through `package-lock.json`. Adding a new npm package requires a one-line justification (purpose, alternative considered) in the commit message body or PR description.
- Do not introduce a package that has had a public supply-chain incident in the last 12 months unless the upstream has published a public post-incident remediation note.
- Treat new typo-adjacent package names with extra scrutiny. If a name is one character away from a popular package, confirm the namespace and publisher before installing.

## Testing Discipline

- Backend tests run as one suite: `python -m pytest backend\tests` locally and in CI. There is no marker-based selection today; if marker discipline is added later, it must be introduced as a single explicit task that updates `pytest.ini`, the test files, and CI together.
- Tests that require GPU, large fixtures, or remote services use module-level skip guards (`pytest.skip(..., allow_module_level=True)` or env-conditional skips) so the default suite stays green on CI hardware.
- Any single test file exceeding 800 lines is a trigger; the next task touching that file must split it along business boundaries.
- High-risk subsystems (OCR engine, LLM router, evidence validation, security guards) require a contract or regression test added in the same change. A change with no test must explain why in the completion report.
- Frontend tests stay on the current minimal runner until a test legitimately needs DOM assertions, async lifecycle, fake timers, or mocking; at that point switch to Vitest as a single migration task.

## Performance Baselines

- Single-page OCR P95 must stay at or under 12 seconds on the DirectML PP-OCRv5 server route on the reference Radeon RX 6600 workstation. CUDA and ROCm targets get their own baselines once a real corpus is wired in.
- Single-field evidence-first extraction P95 must stay at or under 6 seconds on the default DeepSeek v4-flash route.
- Any change that degrades a recorded P95 by more than 30% must be flagged in the completion report with eval profile evidence and either a documented mitigation plan or an explicit acceptance.
- Performance baselines are stored alongside the corresponding eval profile results, not in code; they are evidence, not assertions.

## Precision Tasks

A change is a precision task when it intends to improve OCR text or layout accuracy, field extraction precision/recall, evidence grounding correctness, or LLM prompt fidelity. Precision tasks have stricter evidence rules.

- Every precision task lands with before/after numbers from a relevant eval profile in the same commit:
  - OCR work uses `config/ocr_evaluation_profiles/*.yaml` via `scripts\run-ocr-eval.ps1`.
  - Field extraction work uses `config/evaluation_profiles/*.yaml`. The canonical baseline regenerator is `python scripts\bootstrap-eval-fixtures.py --profile-id <id> --baseline` (rule-only) and `--provider llm --unsafe-eval-allow-remote-context --baseline` (LLM-assisted, eval-only override). The CLI scoring runner is `scripts\run-extraction-eval.ps1` (E0-008 schema `extraction-eval-v1`).
  - On-disk baseline JSON under `config/evaluation_profiles/baselines/<id>.json` (and `<id>_llm.json` for the LLM-assisted run) is the canonical "before" snapshot. Any precision task that changes the metrics must regenerate and commit the baseline in the same change. The companion `test_eval_fixtures.py::test_baseline_file_is_present_and_well_formed` floor must be raised, never lowered, when the baseline improves.
  - When no existing eval profile measures the targeted behavior, extend an eval profile in the same commit or refuse to merge as a precision task. Such a change may still land as a labeled `refactor:` if it asserts no behavior change. Until an extraction eval profile exists for a given behavior, the closest unit or regression test in `backend/tests/test_evidence_first_extraction.py` or `test_extraction_business_cases.py` is acceptable as the "before/after" anchor and must be updated in the same commit.
- Prompt edits are precision changes by default. They must declare:
  1. which fields/groups they target,
  2. which eval cases they were validated against,
  3. the before/after metric (precision, recall, exact-match, or token cost),
  4. whether DeepSeek prompt-cache prefix stability is preserved (a system-prompt rewrite that breaks the prefix invalidates the cost baseline). When the prompt body changes, bump `EVIDENCE_FIRST_PROMPT_VERSION` so cached results from older prompts auto-invalidate.
- Speculative precision ideas without measurement go to `PLAN.md` or `docs/ROADMAP.md` as ideas, not into `dev`.

## Documentation Maintenance

The constitution, roadmap, decision log, and supporting docs are a contract surface in their own right. Keep them in sync through the following rules.

### Single source of truth for outcomes

- A completed task's full "outcome" narrative lives in exactly one place: a dated entry in `docs/DECISIONS.md` when the change records a decision or invariant, otherwise the `PLAN.md` Done section.
- `docs/ROADMAP.md` "Outcome" lines and `PLAN.md` Done entries are summaries of one to three sentences and a link to the DECISIONS anchor when one exists. Do not paste the same multi-paragraph narrative into two files.
- `docs/ARCHITECTURE.md` "Decision Anchors" lists every active DECISIONS entry from the trailing 60 days plus any older entry still cited by current code or docs.

### Identifiers, not hashes

- Documentation must not embed commit hashes. Reference work by ISO date plus task ID, for example "2026-05-18, after E1-010 Phase A and E1-005 close". Commit hashes belong only in `git log` and `docs/DECISIONS.md` promotion notes (where the hash is the artifact).
- "Status as of `<hash>`" headers are forbidden. Use "Status as of `<date>` (task `<id>` closed)" when a snapshot date is meaningful.

### Status fields and supersedence

- Every `docs/DECISIONS.md` entry carries a `Status:` field with one of `active`, `superseded by <YYYY-MM-DD title>`, or `archived (<reason>, <date>)`.
- A decision that supersedes another must update the older entry's `Status:` line in the same commit.
- The DECISIONS.md "Active Index" near the top of the file lists every `active` entry in reverse chronological order. Regenerate it whenever an entry is added, superseded, or archived.

### Markdown size ceiling

- The 500/800-line ceiling in "Personal Codex Workflow" applies to source files. Markdown docs have an 800-line soft ceiling: when crossed, the next docs commit touching the file must split it (typical splits: extract a subsystem appendix, or move archived content to `docs/archive/<topic>.md`).
- `docs/DECISIONS.md`, `docs/ROADMAP.md`, and `PLAN.md` are the most growth-prone; rotate their content per the rules above rather than letting them accumulate.

### Quarterly stale-content sweep

Once per quarter, or before any `dev`-to-`main` promotion that touches more than 200 dirty files, run a documentation sweep:

1. Replace every doc HEAD reference (`Status as of <hash>`, `dev HEAD <hash>`) with a date + task ID.
2. Confirm every roadmap "done" item links to a DECISIONS anchor (or has an explicit "no decision recorded" note).
3. Confirm every "Known Boundary Friction" / "Pending decision" item is still pending; close the resolved ones with a dated decision.
4. Re-verify license entries in `docs/REFERENCE_PROJECTS.md` against upstream URLs and refresh the verified date.
5. If `PLAN.md` "Done" exceeds five entries, move older ones to `docs/PLAN_HISTORY.md`.

Record the sweep as a one-line dated entry in `docs/DECISIONS.md` listing what changed.

## Completion Report

Every completed Codex implementation should report:

- What changed, grouped by behavior rather than a raw file dump.
- Exact validation commands and results.
- What was intentionally not changed.
- Residual risk or the next best task.
