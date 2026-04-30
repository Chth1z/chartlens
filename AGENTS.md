# EYEX Repository Rules

This file is the project constitution for personal Codex-assisted development. Keep it short, concrete, and stricter than memory.

## Personal Codex Workflow

- One session has one primary goal. Do not mix feature work, refactor, UI polish, and infrastructure cleanup in the same pass unless the user explicitly asks for a combined change.
- Start every non-trivial task by reading this file, inspecting the relevant files, and checking `git status --short`. Do not work from memory.
- For work likely to exceed 30 minutes or touch multiple subsystems, provide a short plan before editing. Small focused fixes may be implemented directly.
- Prefer test-first or verification-first changes for behavior work: write or adjust the failing test/check, confirm it fails, then change implementation.
- Remove old logic, routes, fields, and environment variables by default. Do not add compatibility layers unless a real external dependency exists; if compatibility is kept, document its deletion condition.
- If unrelated dirty files exist, leave them alone. If they affect the task, explain the conflict before changing the affected area.

## Personal GitHub Management

- Treat `main` as the stable upstream branch and `dev` as the personal integration branch for this full ChartLens upgrade.
- Do not push directly to `main`. Merge `dev` into `main` only after the full default verification passes and the branch diff has been reviewed.
- Use `codex/<goal>` branches off `dev` for future focused tasks. Merge them back into `dev` after their task-specific verification passes.
- One task branch should represent one primary goal with a concrete verification story. If the work grows across unrelated areas, split it before merging.
- Keep PRs draft by default for high-risk changes; merge only after backend tests, frontend tests, frontend build, and the relevant residual scan pass.
- Never stage `.env`, runtime state, model downloads, caches, generated test output, or frontend build artifacts. Runtime data belongs in ignored directories such as `var/`, `storage/`, `logs/`, `output/`, and `tmp/`.
- Every pushed branch must have a completion note covering changed behavior, validation commands, intentionally skipped areas, and residual risks.
- High-impact decisions for API contracts, OCR/LLM routing, evidence integrity, storage, security, or GitHub workflow must be recorded in `docs/DECISIONS.md` before or with the branch.

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

## Quality Gates

- Backend: `python -m pytest backend\tests`
- Frontend tests: `cd frontend; npm test`
- Frontend build: `cd frontend; npm run build`
- Residual scan after cleanup work: search for old route names, old fields, `legacy`, `latest`, duplicate API clients, and generated caches.
- High-risk LLM/OCR/evidence changes also need an eval profile run or a documented reason why no eval data applies.

## Completion Report

Every completed Codex implementation should report:

- What changed, grouped by behavior rather than a raw file dump.
- Exact validation commands and results.
- What was intentionally not changed.
- Residual risk or the next best task.
