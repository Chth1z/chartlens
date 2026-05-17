# EYEX Repository Rules

This file is the project constitution for personal Codex-assisted development. Keep it short, concrete, and stricter than memory.

## Personal Codex Workflow

- One session has one primary goal. Do not mix feature work, refactor, UI polish, and infrastructure cleanup in the same pass unless the user explicitly asks for a combined change.
- Start every non-trivial task by reading this file, inspecting the relevant files, and checking `git status --short`. Do not work from memory.
- For work likely to exceed 30 minutes or touch multiple subsystems, provide a short plan before editing. Small focused fixes may be implemented directly.
- Prefer test-first or verification-first changes for behavior work: write or adjust the failing test/check, confirm it fails, then change implementation.
- Remove old logic, routes, fields, and environment variables by default. Do not add compatibility layers unless a real external dependency exists; if compatibility is kept, document its deletion condition.
- If unrelated dirty files exist, leave them alone. If they affect the task, explain the conflict before changing the affected area.
- Single-file complexity ceiling: any backend Python file or frontend `.ts`/`.tsx` file exceeding 500 lines is a trigger; the next task touching that file must include a split. The pre-split task must still pass full quality gates.
- Major architecture direction changes (introducing or removing `application/`, reshaping `services/` subpackages, swapping the primary data flow) must be recorded in `docs/DECISIONS.md` before code lands.
- After any approach has failed twice, stop incremental patching and write a one-line root-cause hypothesis before the third attempt.

## Personal GitHub Management

- Treat `main` as the stable upstream branch and `dev` as the personal integration branch for this full ChartLens upgrade.
- Do not push directly to `main`. Merge `dev` into `main` only after the full default verification passes and the branch diff has been reviewed.
- Use `codex/<goal>` branches off `dev` for future focused tasks. Merge them back into `dev` after their task-specific verification passes.
- One task branch should represent one primary goal with a concrete verification story. If the work grows across unrelated areas, split it before merging.
- Keep PRs draft by default for high-risk changes; merge only after backend tests, frontend tests, frontend build, and the relevant residual scan pass.
- Never stage `.env`, runtime state, model downloads, caches, generated test output, or frontend build artifacts. Runtime data belongs in ignored directories such as `var/`, `storage/`, `logs/`, `output/`, and `tmp/`.
- Every pushed branch must have a completion note covering changed behavior, validation commands, intentionally skipped areas, and residual risks.
- High-impact decisions for API contracts, OCR/LLM routing, evidence integrity, storage, security, or GitHub workflow must be recorded in `docs/DECISIONS.md` before or with the branch.
- Long-running branches (`dev`, any `codex/<goal>`) that accumulate more than 60 dirty files must stop new feature work until the dirty set is merged, split, or discarded. Mixing in fresh refactors on top of that state is forbidden.
- Each `codex/<goal>` branch has a 2-week life cap. If it is still open after that, write the cause in `PLAN.md` and either close it or split it; do not silently let task branches age.

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

- `config/` contains versioned clinical, extraction, export, validation, OCR, and model profile configuration.
- `backend/app/` contains application code only. Do not put editable project configuration back under `backend/app/data`.
- `var/` is runtime state: SQLite databases, uploads, OCR cache, provider settings, local secrets, downloaded models, and other generated artifacts. It is ignored.
- `storage/`, `logs/`, `output/`, and `tmp/` are previous or temporary runtime locations and remain ignored.
- `frontend/src/shared/api/client.ts` is the canonical frontend API client. Do not reintroduce parallel clients under `frontend/src/lib`.
- `PLAN.md` is the lightweight personal task board. Do not replace it with a heavy issue process.
- `docs/DECISIONS.md` is the short decision log for high-impact architecture, data, security, provider, OCR, or workflow decisions.

## Architecture Boundaries

- Keep API routers thin: request validation, HTTP status mapping, and response assembly only.
- Frontend-facing backend endpoints must declare an explicit `response_model`; OpenAPI is the API contract source for the frontend boundary.
- Frontend API calls must go through `frontend/src/shared/api/client.ts`, normalize FastAPI errors as `ApiError`, and avoid direct ad hoc `fetch` calls.
- Keep model provider protocol adapters separate from clinical extraction rules.
- Keep OCR routing controlled by `config/ocr_profiles/*.yaml`; do not add runtime engine override environment variables.
- Non-`unknown` extraction results must keep evidence spans grounded in the de-identified `DocumentIR`.
- Config is product behavior. Changes under `config/` require config contract tests.
- Do not introduce abstractions just to hide old behavior. Add an abstraction only when it reduces real duplication or isolates a stable boundary.
- LLM calls must go through the LLM provider router (currently `backend/app/services/llm_provider/`). Business pipelines must not import a specific protocol adapter directly; routing, fallback, and key cooldown policy belong to the router layer.
- OCR engines under `backend/app/services/ocr_engine/` only produce raw and single-engine canonical output. Profile-driven same-line merging, paragraph reflow, screen-chrome removal, patient-header detection, and key-value derivation belong to `backend/app/services/layout_normalizer.py`.
- Any change to `processing_runs`, `processing_events`, or `model_calls` schema is an observability contract change and must be recorded in `docs/DECISIONS.md`.
- `ExtractionCandidate`, `EvidencePack`, `EvidenceCandidate`, and `DocumentIRBlock` go through a quarterly dead-field prune: any Pydantic field with no read site in `services/` or `frontend/` must be removed.

## Quality Gates

- Backend: `python -m pytest backend\tests`
- Frontend tests: `cd frontend; npm test`
- Frontend build: `cd frontend; npm run build`
- Governance scan after cleanup work: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`
- High-risk LLM/OCR/evidence changes also need an eval profile run or a documented reason why no eval data applies.

## Dependency Management

- Backend `requirements*.txt` must pin exact versions. New dependencies must be checked for upstream activity (one update in the last year), license compatibility for personal use, and absence of known supply-chain incidents.
- Frontend dependencies are locked through `package-lock.json`. Adding a new npm package requires a one-line justification (purpose, alternative considered) in the PR description.
- Do not introduce a package that has had a public supply-chain incident in the last 12 months unless the upstream has published a public post-incident remediation note.
- Treat new typo-adjacent package names with extra scrutiny. If a name is one character away from a popular package, confirm the namespace and publisher before installing.

## Testing Discipline

- Backend tests are tagged with pytest markers: `unit`, `contract`, `regression`, `slow`, `needs_gpu`. Default CI runs `unit` and `contract`. `regression`, `slow`, and `needs_gpu` run locally or in dedicated workflows.
- Any single test file exceeding 800 lines is a trigger; the next task touching that file must split it along business boundaries.
- High-risk subsystems (OCR engine, LLM router, evidence validation, security guards) require a contract or regression test added in the same change. A change with no test must explain why in the completion report.
- Frontend tests stay on the current minimal runner until a test legitimately needs DOM assertions, async lifecycle, fake timers, or mocking; at that point switch to Vitest as a single migration task.

## Performance Baselines

- Single-page OCR P95 must stay at or under 12 seconds on the DirectML PP-OCRv5 server route on the reference Radeon RX 6600 workstation. CUDA and ROCm targets get their own baselines once a real corpus is wired in.
- Single-field evidence-first extraction P95 must stay at or under 6 seconds on the default DeepSeek v4-flash route.
- Any change that degrades a recorded P95 by more than 30% must be flagged in the completion report with eval profile evidence and either a documented mitigation plan or an explicit acceptance.
- Performance baselines are stored alongside the corresponding eval profile results, not in code; they are evidence, not assertions.

## Completion Report

Every completed Codex implementation should report:

- What changed, grouped by behavior rather than a raw file dump.
- Exact validation commands and results.
- What was intentionally not changed.
- Residual risk or the next best task.
