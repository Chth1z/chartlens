# Personal Codex Workflow

Use this when starting a new Codex task for EYEX.

## Prompt Template

```text
Goal:
Do not change:
Old logic policy: delete / keep until <condition>
Required verification:
Completion report: changed files + validation results + risks + next best step
```

## Session Checklist

- Start with `git status --short`, `AGENTS.md`, and the files relevant to the goal.
- Keep one primary goal per session.
- For behavior changes, create or update the test/check first and confirm it fails for the expected reason.
- Make the smallest change that satisfies the goal.
- Delete stale code instead of wrapping it in compatibility abstractions.
- Run the required verification commands before completion.
- Clean generated caches and temporary outputs that are not meant to stay in the workspace.

## GitHub Branch Checklist

- Integration branch: `dev`.
- Task branch: `codex/<short-goal>` from `dev`.
- Branch scope: `dev` holds the full upgrade line; each `codex/<short-goal>` branch holds one primary task only.
- Before staging: inspect `git status --short --branch` and confirm no ignored runtime or secret files are included.
- Before commit: run the task-specific checks and the default verification unless the task is docs-only.
- Before push: scan for old route names, old fields, duplicate API clients, generated caches, `legacy`, and `latest` where relevant.
- After push: report branch name, commit hash, validation output, and residual risks. Use a draft PR for high-risk or cross-module work. Do not merge `dev` into `main` until the full verification is clean and the diff is intentionally accepted.

## Codex Management Constraints

- Prefer small verifiable changes over broad refactors.
- Delete obsolete code paths during cleanup instead of adding compatibility layers.
- Add or update tests before implementation for behavior changes.
- Keep API contract changes explicit: backend `response_model`, frontend canonical client, and no parallel client entrypoints.
- Use `PLAN.md` only for concrete tasks with triggers and done conditions; do not add vague technical debt notes.
- Record architectural choices in `docs/DECISIONS.md` only when they affect future work.

## Default Verification

```powershell
python -m pytest backend\tests
cd frontend
npm test
npm run build
```

For high-risk LLM, OCR, evidence, export, privacy, or config changes, add the relevant eval/profile test and include the metric impact in the completion report.
