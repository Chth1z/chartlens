# ChartLens Architecture

ChartLens is a single-machine clinical research extraction system. It is not a general document platform and does not maintain Docker, Postgres, Redis, or RQ deployment paths.

## Target Shape

- `domain/` contains pure business models and rules: clinical OCR blocks, fragments, field definitions, extraction results, confidence, de-identification, and auth identity value objects.
- `application/` contains use cases and ports. Use cases orchestrate domain behavior through protocols only.
- `infrastructure/` contains adapters: SQLite ORM/repositories, local files, local task queue, OCR engines, model providers, YAML config loading, cache, maintenance, token cache, and Excel export.
- `interfaces/http/` contains FastAPI routes and HTTP auth/session handling. Routes parse HTTP input, call use cases, and shape HTTP responses.
- `composition/` is the dependency wiring root. It is the place where FastAPI dependencies create infrastructure adapters for application ports.

## Dependency Rules

- `domain` must not import FastAPI, SQLAlchemy, `app.interfaces`, `app.infrastructure`, `app.core`, or `app.composition`.
- `application` must not import FastAPI, SQLAlchemy, `app.interfaces`, `app.infrastructure`, `app.core`, or `app.composition`.
- HTTP routes must not import SQLAlchemy or SQLite ORM models directly. Database access goes through repository adapters.
- Legacy import paths are removed and must not return: `app.services`, `app.api`, `app.schemas`, `app.models`, `app.core.database`.
- New functionality starts with an application use case and port first; infrastructure and HTTP adapters are added around it.

## Runtime Boundaries

- SQLite is the only supported runtime database.
- Local thread queue is the only supported background processing path.
- Browser cookie session and local ChatGPT/Codex model token cache are separate concerns.
- YAML configuration is read-only through the UI in the current version; validation is supported, online editing is not.
- Demo data is not part of runtime UI. Use test fixtures or seed scripts if sample data is needed.

## Verification

Before considering architecture work complete:

- `python -m pytest backend/tests`
- `cd frontend && npm run build`
- `start.cmd`, then `diagnose.cmd`
- Scan for legacy imports and deleted paths covered by `backend/tests/test_architecture_boundaries.py`.
