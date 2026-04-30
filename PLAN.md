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

### todo Split provider responsibilities on next provider change

- Goal: Separate model protocol adapters, fallback routing, prompt construction, response parsing, and LLM cache when `backend/app/services/provider.py` is next changed for provider behavior.
- Out of scope: Do not change model semantics or prompt contract during the first split.
- Acceptance commands: `python -m pytest backend\tests\test_provider_fallback.py backend\tests\test_core_business_optimization.py`
- Risk: Provider fallback and cache behavior can regress silently.
- Trigger: Any new provider, fallback, prompt, or cache change.
- Done condition: Provider-specific HTTP code no longer shares a file with clinical local extraction helpers.

### todo Move persistent processing jobs out of process memory

- Goal: Replace process-local case queue assumptions with a persistent job record that can recover queued/running work after restart.
- Out of scope: Do not introduce Redis or external queue infrastructure for the first version.
- Acceptance commands: `python -m pytest backend\tests`
- Risk: Uploads can be marked queued/extracting without a recoverable worker after process restart.
- Trigger: Before relying on EYEX for batches that cannot be manually re-uploaded.
- Done condition: Queued/running cases can be resumed or explicitly marked failed with a diagnostic reason on startup.

### todo Add database migration baseline before schema expansion

- Goal: Introduce a lightweight migration path before adding more SQLite tables or columns.
- Out of scope: Do not migrate to Postgres in this task.
- Acceptance commands: `python -m pytest backend\tests`
- Risk: Manual `create_all` and ad hoc `ALTER TABLE` will become unsafe as review, eval, and job history grows.
- Trigger: Before adding the next persistent table or non-null column.
- Done condition: Fresh DB and existing DB upgrade through the same migration command or startup path.

### todo Convert frontend tests to a standard runner when assertions grow

- Goal: Move current script-based frontend tests to Vitest when UI/domain frontend tests need async, DOM, or snapshots.
- Out of scope: Do not add a browser E2E suite in this task.
- Acceptance commands: `cd frontend; npm test; npm run build`
- Risk: The current tiny runner is intentionally minimal and will become awkward for richer tests.
- Trigger: The next frontend test that needs mocking, fake timers, DOM assertions, or async test lifecycle.
- Done condition: `npm test` uses a standard runner and keeps the current four tests passing.

## Done

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
