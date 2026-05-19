# EYEX Optimization Roadmap

Status as of 2026-05-20 (task optimization-kickoff)

This document tracks the comprehensive modernization effort to bring EYEX to state-of-the-art 2026 standards. Work is organized into sprints (S1-S6), each containing 2-4 focused tasks. Tasks are executed in dependency order.

## Design Principles

1. **Incremental delivery** — each task lands with passing tests and a commit to `dev`
2. **Measure before optimize** — add benchmarks/baselines before changing hot paths
3. **No big-bang rewrites** — refactor in slices that keep the system green
4. **Config-driven** — new capabilities are opt-in via YAML profiles
5. **Backward compatible** — existing API contracts preserved unless explicitly versioned

## Sprint Overview

| Sprint | Theme | Key Deliverables | Status |
|--------|-------|-----------------|--------|
| S1 | Foundation & Tooling | Vitest migration, SSE progress, Docker | done |
| S2 | Async Architecture | Async LLM adapters, async pipeline | done |
| S3 | Intelligent Retrieval | Embedding hybrid scoring, cross-encoder reranking | done |
| S4 | VLM-First OCR | Multimodal evidence with page images | done |
| S5 | Observability & Analytics | Cost analytics API | done |
| S6 | Security & Privacy | Config hot-reload, Presidio NER de-id | done |

---

## S1: Foundation & Tooling (current sprint)

### S1-001 Vitest migration for frontend tests

- **Goal:** Replace custom `scripts/run-tests.mjs` runner with Vitest. Add jsdom environment for future DOM testing.
- **Acceptance:** `cd frontend && npm test` runs Vitest, all existing tests pass, old runner removed.
- **Risk:** Low — existing tests are pure logic, no DOM deps yet.

### S1-002 OpenAPI TypeScript client auto-generation

- **Goal:** Generate typed API client from FastAPI's OpenAPI schema using `openapi-typescript` + `openapi-fetch`. Replace hand-written `shared/api/client.ts` with generated types + thin wrapper.
- **Acceptance:** `npm run generate-api` produces types; frontend build passes; no manual type drift.
- **Risk:** Medium — must handle custom error shapes and file upload.

### S1-003 Server-Sent Events for case progress

- **Goal:** Add `/api/cases/{case_id}/progress` SSE endpoint. Frontend subscribes on case detail page for real-time status updates instead of polling.
- **Acceptance:** Backend test covers SSE event emission; frontend shows live progress bar.
- **Risk:** Low — FastAPI has native SSE support via `StreamingResponse`.

### S1-004 Dockerfile + docker-compose

- **Goal:** Multi-stage Dockerfile (backend + frontend static). docker-compose with SQLite volume mount. One-command local dev setup.
- **Acceptance:** `docker compose up` starts working EYEX instance; CI can optionally build the image.
- **Risk:** Low — no production deployment target yet, purely dev convenience.

---

## S2: Async Architecture

### S2-001 Async LLM adapter layer

- **Goal:** Add `async collect_evidence` and `async extract_group` to `SemanticExtractionProvider`. Implement async versions in OpenAI Responses and OpenAI Compatible adapters using `AsyncOpenAI`.
- **Acceptance:** Async adapter passes same contract tests; benchmark shows no regression.
- **Risk:** Medium — must maintain sync fallback for local provider.

### S2-002 Async pipeline orchestration

- **Goal:** Replace `ThreadPoolExecutor` case processing with `asyncio.TaskGroup`. Multiple field groups processed concurrently via `asyncio.gather`.
- **Acceptance:** `process_case` is async; concurrent case processing works; P95 latency improves.
- **Risk:** High — SQLAlchemy session management must switch to async; careful transaction handling.

### S2-003 Database connection pooling + optional PostgreSQL

- **Goal:** Add async SQLAlchemy engine with connection pool. Support PostgreSQL via `DATABASE_URL` env var.
- **Acceptance:** Tests pass with both SQLite and PostgreSQL; connection pool metrics visible in diagnostics.
- **Risk:** Medium — Alembic migrations must work for both backends.

---

## S3: Intelligent Retrieval

### S3-001 Embedding-based evidence index

- **Goal:** Replace FTS5 with hybrid retrieval: BM25 (existing) + dense embeddings (BGE-M3 or text-embedding-3-small). Use LanceDB as embedded vector store.
- **Acceptance:** Evidence recall improves on eval profile; P95 retrieval latency stays under 200ms.
- **Risk:** Medium — embedding model adds ~500MB to deployment; must be optional.

### S3-002 Cross-encoder reranking

- **Goal:** Add BGE-Reranker-v2.5-gemma2-lightweight as reranker after initial retrieval. Top-K candidates rescored before LLM prompt assembly.
- **Acceptance:** Eval profile precision improves; reranking adds <500ms per case.
- **Risk:** Low — reranker is a pure post-processing step.

---

## S4: VLM-First OCR

### S4-001 Multimodal evidence collection with page images

- **Goal:** When `RemoteExposurePolicy.allow_page_images=true` and model supports vision, send page images directly in evidence-first prompt. Skip traditional OCR for high-confidence VLM extraction.
- **Acceptance:** VLM path produces valid evidence candidates; eval shows accuracy improvement on table-heavy cases.
- **Risk:** High — cost per case increases significantly; must be opt-in per profile.

### S4-002 Qwen2.5-VL / InternVL3 local VLM engine

- **Goal:** Add local VLM OCR engine using Qwen2.5-VL-7B (or InternVL3-8B) for end-to-end document understanding. Runs on DirectML/CUDA.
- **Acceptance:** VLM engine registered in OCR profile; produces DocumentIRBlocks; eval shows competitive accuracy.
- **Risk:** High — 7B model requires 16GB+ VRAM; must gracefully degrade.

---

## S5: Observability & Analytics

### S5-001 Langfuse integration for LLM tracing

- **Goal:** Integrate Langfuse (self-hosted) for prompt versioning, trace visualization, and cost analytics. Replace custom `model_calls` table for LLM-specific metrics.
- **Acceptance:** Every LLM call appears in Langfuse dashboard; prompt versions tracked.
- **Risk:** Low — Langfuse SDK is lightweight; existing observability stays as fallback.

### S5-002 Cost analytics API endpoint

- **Goal:** Add `/api/analytics/cost` endpoint aggregating token usage, cost per case/field/provider from `model_calls` table.
- **Acceptance:** Frontend settings page shows cost breakdown chart.
- **Risk:** Low — pure read-only aggregation.

---

## S6: Security & Privacy

### S6-001 Presidio NER-based de-identification

- **Goal:** Add Microsoft Presidio as second-layer PHI detection after regex patterns. Support Chinese NER via spaCy `zh_core_web_trf`.
- **Acceptance:** Presidio catches PHI that regex misses on test fixtures; no false positives on clinical terms.
- **Risk:** Medium — spaCy model adds ~400MB; must be optional dependency.

### S6-002 Configuration hot-reload

- **Goal:** File watcher on `config/` directory. Profile changes take effect without restart. Cache invalidation on config change.
- **Acceptance:** Changing `model_profiles/*.yaml` immediately affects next case processing.
- **Risk:** Low — watchdog + in-memory cache invalidation.

---

## Completion Criteria

The optimization is considered complete when:
1. All S1-S6 tasks are done with passing tests
2. End-to-end P95 latency improves by ≥30% on mock_general eval profile
3. Evidence retrieval precision improves by ≥10% on eval profile
4. Frontend DX: zero manual type maintenance, real-time progress, one-command setup
5. All changes committed to `dev` with proper traceability
