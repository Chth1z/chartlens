# EYEX Modernization Plan

This file is the rolling master plan for the SOTA-alignment program kicked off on 2026-05-19. It complements `docs/ROADMAP.md` (E0/E1/E2 precision-driven plan) by tracking the cross-cutting modernization iterations that target LLM orchestration, async runtime, observability, supply-chain hardening, retrieval, and frontend state management.

When this file and `docs/ROADMAP.md` overlap (for example E1-003 retry-with-validation-feedback also belongs to the async runtime iteration), the roadmap ID stays authoritative for precision acceptance and this file tracks the cross-cutting modernization shape. When this file and `AGENTS.md` disagree, `AGENTS.md` is the rule.

## Overall Goal

Bring EYEX up to current SOTA across these axes without regressing the precision baselines:

- LLM provider routing by **capability**, not by hand-crafted prompt workarounds.
- Async backend I/O end-to-end.
- Dependency lockfile + supply-chain audit in CI.
- OpenTelemetry traces and Langfuse/OTLP export wired through the durable ledger.
- Per-case in-process FTS index reuse.
- Frontend server state managed by TanStack Query.
- Dense embedding + reranker as the eval-time second source for evidence retrieval.
- LLM-as-judge faithfulness evaluator.

## Success Criteria for the Program

1. Every LLM call uses the strongest structured-output mode the provider supports; cost on cache misses drops measurably without precision regression.
2. Backend LLM and HTTP I/O is async; concurrent field-level dispatch is observable and tested.
3. CI runs lockfile-pinned installs (`--require-hashes`), `pip-audit`, `bandit`, `npm audit signatures`. SBOM is generated.
4. OpenTelemetry traces with `case_id` / `run_id` / `stage` attributes flow through OTLP; the durable ledger remains the system of record but the trace view is one click away.
5. `evidence.py:_fts_scores` no longer rebuilds the FTS index per field; an evaluation run records the wall-clock improvement.
6. `useChartLensState.ts` drops below 300 lines through TanStack Query adoption; race-guard plumbing is removed.
7. Dense embedding + reranker land as a parallel evidence source in `medical_inpatient_zh` eval; precision delta is recorded.
8. LLM-as-judge evaluator runs alongside E0-008 and catches at least one previously-undetected evidence-correct-but-semantically-wrong case in `mock_general`.
9. Every iteration ends green: `python -m pytest backend\tests`, `npm test`, `npm run build`, governance scan, baseline JSON unchanged or improved.

## Operating Loop (master agent)

Each iteration follows the same shape:

1. **Plan**: master agent writes a focused PLAN.md task with goal / out of scope / acceptance commands / risk / done condition. Single primary goal per iteration, scoped for one focused session.
2. **Execute**: master agent delegates to a sub-agent (`general-task-execution` or `context-gatherer` first when discovery is needed). Sub-agent reads only the files it needs, makes the change, runs the acceptance commands.
3. **Verify**: master agent re-runs the acceptance commands itself, checks baseline JSON is preserved or improved, scans governance.
4. **Commit**: standard commit footer (`Refs:`, `Verification:`).
5. **Replan**: master agent writes the next iteration based on the result, lessons, and current AGENTS.md / ROADMAP / DECISIONS state.

The master agent does not silently broaden scope mid-iteration. If a sub-agent surfaces an unexpected blocker, the master agent stops, records the blocker as a separate todo, and either re-scopes the current iteration or pivots.

## Iterations

### Status legend

- `planned` — written here, not yet active
- `active` — current iteration
- `done` — closed; outcome recorded below

### M1-001 — Provider-capability-aware structured output routing (done 2026-05-19)

- Goal: stop carrying the "contiguous-substring" and "placeholder-not-value" prompt rules as plain-text prose in the system prompt, and start enforcing them through the strongest structured-output mode each provider supports. Add a `structured_output_mode` field on `ModelProfile` with values `json_schema` (strict), `json_object`, `tools`, `text`. The runtime tries the strongest mode the profile declares; on a 400-class capability error it falls back to the next mode and records the downgrade in `model_calls.usage`.
- Out of scope: prompt rewrites (E1-001 v4), provider catalog changes (mainstream.yaml model ids), changing the actual JSON schema of evidence candidates.
- Why now: every other modernization iteration leans on structured-output stability (async pipelining especially needs deterministic JSON shape). This is also the highest-leverage precision lever still on the table — the v3.x prompt iterations were essentially compensating for missing schema enforcement on chat-completion endpoints.
- Acceptance commands: `python -m pytest backend\tests`; `cd frontend; npm test; npm run build`; `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1`. Rule baseline 153/159 unchanged byte-for-byte. LLM baseline ≥ 158/159 on the cache-cleared run.
- Risk: a provider whose strict json_schema differs subtly from EYEX's schema returns 400; the fallback path must be exercised by unit tests.
- Done condition: `ModelProfile.structured_output_mode` is declared and serialized; OpenAI-compatible adapter detects strict-mode capability per `model_profiles/*.yaml`; existing tests still pass; new contract test covers the capability fallback ladder; baseline JSON unchanged.
- Outcome (2026-05-19): closed in one focused session. 11 new contract tests in `backend/tests/test_provider_structured_output.py`. 7 model-profile YAMLs declare explicit modes (`json_schema` for openai_structured / deepseek_v4_flash / deepseek_v4_pro; `json_object` for openrouter_auto / ollama_local / openai_compatible_custom; `text` for local_disabled). The OpenAI-compatible adapter shares a `_run_chat_request` helper between `extract_group` and `collect_evidence` and walks the `json_schema → json_object → text` downgrade ladder once on a 400-class capability error, recording the downgrade reason in `last_usage`. Cache keys include `structured_output_mode` so flipping modes invalidates cached results. 355 backend tests pass (was 344); 9 frontend tests pass; build clean; governance clean; rule baseline 153/159 byte-equivalent. Anchor: PLAN.md Done.

### M1-002 — Async LLM provider layer (next, planned)

- Goal: convert `OpenAICompatibleChatProvider`, `OpenAIResponsesProvider`, `AnthropicMessagesProvider`, `GoogleGeminiProvider` to `AsyncOpenAI` / `httpx.AsyncClient`. Keep the existing sync method names as thin wrappers that `asyncio.run` the async core. Enable concurrent field-level dispatch in `pipeline_evidence_first.collect_evidence` by chunking fields and `asyncio.gather`-ing per chunk.
- Out of scope: FastAPI route async migration; SQLAlchemy async session migration; pipeline orchestration restructure beyond the chunked dispatch.
- Acceptance: full backend tests pass; LLM baseline within ±1 case of current (cache-cleared); a new perf test asserts that 10 concurrent collect_evidence calls share one client and complete in less than 60% of the serialized time.

### M1-003 — Dependency lockfile + supply-chain audit (planned)

- Goal: migrate backend to `uv` (`pyproject.toml` + `uv.lock` + `--require-hashes`); add `pip-audit`, `bandit`, and `npm audit signatures` to CI; emit a CycloneDX SBOM artifact per CI run.
- Out of scope: dropping any current dependency.
- Acceptance: CI green; `uv pip install --require-hashes` succeeds; SBOM artifact uploaded.

### M1-004 — OpenTelemetry traces (planned)

- Goal: wire `opentelemetry-instrumentation-fastapi` + `opentelemetry-instrumentation-httpx`, mirror every `ProcessingTrace.step` and `record_model_call` as an OTel span carrying `case_id`, `run_id`, `stage`, `provider`, `model`, `cache_status`. Default exporter is OTLP-stdout; a `EYEX_OTEL_ENDPOINT` env var enables OTLP-grpc for local Tempo/Jaeger or a Langfuse OTel ingest.
- Out of scope: hosted observability backend choice; cost tracking enrichment beyond what `model_calls.cost_usd` already carries.
- Acceptance: spans visible in stdout exporter; `model_calls` rows still match the OTel spans 1:1 in the test suite.

### M1-005 — In-process FTS index per case (planned)

- Goal: build the SQLite FTS5 index once per case during `build_document_context` and reuse it for every `build_evidence_packs` call inside that case. Replace `evidence.py:_fts_scores`'s `sqlite3.connect(":memory:")` per-field cost.
- Out of scope: switching to `whoosh` or `tantivy`.
- Acceptance: rule baseline unchanged; eval runner reports a wall-clock improvement on `mock_general` (target: 30%+ reduction in extraction stage time).

### M1-006 — TanStack Query frontend server state (planned)

- Goal: replace `useChartLensState.ts` polling/refresh/race-guard with TanStack Query. `caseSwitching.test.ts` and the apiClient surface stay stable.
- Out of scope: full Zustand migration; Tailwind / shadcn migration.
- Acceptance: `useChartLensState.ts` drops below 300 lines; existing 9 frontend tests still pass; `npm run build` clean.

### M2-001 — Dense embedding + reranker for evidence (planned)

- Goal: introduce `bge-m3` (multilingual embedding) + `bge-reranker-v2-m3` as a parallel evidence-retrieval source under the eval profile. The runtime path stays BM25/FTS5 by default; the new path is opt-in via `evaluation_profiles/medical_inpatient_zh.yaml` plus `EYEX_EVAL_RETRIEVAL=dense`.
- Out of scope: replacing the BM25 path; running embedding inference in the main backend.
- Acceptance: dense+rerank report committed under `config/evaluation_profiles/baselines/medical_inpatient_zh_dense.json`; precision delta documented in this file.

### M2-002 — LLM-as-judge faithfulness evaluator (planned)

- Goal: extend the E0-008 runner with an optional `--judge-model` flag that, after extraction, asks a third-party model to score (DocumentIRBlock, evidence_text, normalized_code) faithfulness 1-5. Aggregated as a new metric `evidence_faithfulness_mean`.
- Out of scope: training a judge; live runtime use.
- Acceptance: judge run on `mock_general` produces the metric; at least one historical false-positive in earlier baselines is rediscovered.

## Decision Anchors

- 2026-05-19 — Rolling SOTA modernization plan introduced; iterations are independent of E0/E1/E2 precision tasks but commit to the same baseline-preserving discipline.
