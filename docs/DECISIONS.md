# EYEX Decision Log

Use this file only for decisions that affect architecture, data contracts, security/privacy, OCR/LLM behavior, project workflow, or deletion/compatibility policy. Keep entries short.

## Template

```markdown
## YYYY-MM-DD - <decision title>

- Decision:
- Why:
- Rejected:
- Revisit when:
```

## 2026-04-30 - Personal Codex governance over team process

- Decision: Use `AGENTS.md` as the project constitution, `PLAN.md` as a lightweight task board, and this file as the short decision log.
- Why: EYEX is currently a personal Codex-assisted project, so low-friction written rules are more useful than heavyweight issue, PR, and ADR processes.
- Rejected: Formal team issue workflow, long ADR documents, and broad multi-topic refactor sessions.
- Revisit when: Another regular contributor joins, EYEX is used for real multi-user operations, or release management needs explicit approvals.

## 2026-04-30 - Delete stale compatibility by default

- Decision: Old fields, routes, environment variables, and payload shapes are deleted unless a real external dependency requires a temporary compatibility path.
- Why: The project is still evolving quickly; compatibility layers would preserve mistakes and raise future change cost.
- Rejected: Long-lived adapters that translate legacy shapes into canonical shapes without a deletion condition.
- Revisit when: EYEX exposes a stable external API or has users outside the local development environment.

## 2026-04-30 - OCR engine order is profile-driven

- Decision: OCR engine order is controlled by `config/ocr_profiles/*.yaml`; runtime engine override environment variables are not part of the app contract.
- Why: OCR routing is product behavior and must be reviewable, testable, and versioned with configuration.
- Rejected: A runtime environment variable that directly overrides OCR engine order.
- Revisit when: A deployment needs safe runtime OCR routing changes, with tests and an explicit rollback story.

## 2026-04-30 - GitHub branches are the personal Codex control boundary

- Decision: Keep `main` stable, use `dev` as the personal integration branch for the full ChartLens upgrade, and use `codex/<goal>` branches from `dev` for focused future tasks.
- Why: This repository is being upgraded substantially from the previous ChartLens baseline. A named `dev` branch communicates that it is the active integration line, while task branches still keep Codex sessions bounded.
- Rejected: Direct pushes to `main`, one-off import branch names for the long-lived upgrade line, and large mixed-purpose task branches.
- Revisit when: More contributors start changing the repository or the project needs release branches.
