# EYEX Architecture

This document is the authoritative description of the EYEX runtime. When `AGENTS.md` and this file disagree, `AGENTS.md` is the rule and this file is the explanation.

The pipeline goal is structured field extraction from clinical documents (image / PDF / native text) with full evidence traceability and a hard local privacy boundary. Everything else (config layering, OCR routing, LLM routing, observability) exists to make that goal verifiable.

## Main Pipeline

```text
upload  ->  raw OCR / native text  ->  layout normalization  ->  de-identified DocumentIR
                                                                        |
                                                                        v
                                                                DocumentContext
                                                                        |
                                                                        v
                                                          evidence collection
                                                          (local rule + remote LLM)
                                                                        |
                                                                        v
                                                              field adjudication
                                                                        |
                                                                        v
                                                       validation guardrails
                                                                        |
                                                                        v
                                            ValidatedFieldResult (auto-accepted / needs_review)
                                                                        |
                                                                        v
                                              human review  ->  Excel export + audit ledger
```

Every stage writes to the observability ledger (`processing_runs`, `processing_events`, `model_calls`) so the same chain of custody can be reconstructed after restart.

## Layering

EYEX has six runtime layers. Each has a single primary responsibility.

| Layer | Module roots | Responsibility |
| --- | --- | --- |
| API | `backend/app/api/` | HTTP contracts, auth gate, request validation, response assembly. Routers stay thin. |
| Core | `backend/app/core/` | Settings (Pydantic settings), database engine, ORM models, config loader. |
| Domain | `backend/app/domain/` | Pydantic data contracts: `DocumentIR`, `DocumentContext`, `ExtractionSchema`, `EvidenceCandidate`, `FieldDecision`, `ExtractionCandidate`, `ValidatedFieldResult`, `ModelProfile`, `OcrProfile`, `DocumentProfile`. |
| Services | `backend/app/services/` | Business logic. Subdivided by responsibility (see next section). |
| OCR sidecar | `backend/ocr_sidecar/` | A separate FastAPI process running heavy OCR engines in `.venv-ocr`. Reached over HTTP through `EYEX_OCR_DOCUMENT_AI_URL`. |
| Frontend | `frontend/src/` | React + Vite UI. Single API client at `frontend/src/shared/api/client.ts`. |

## Services Layout

Today's `backend/app/services/` is intentionally flat. The application/services layout decision is still in `PLAN.md`; the description below reflects current code, not the target layout.

| Module | Role |
| --- | --- |
| `pipeline.py` | Top-level orchestration: case state machine, stage timing, error formatting, persistence. Owns the `_extract_document_evidence_first` rule_pre_accepted partition (high-confidence `rule_shortcut` fields skip the LLM router; see `docs/DECISIONS.md` 2026-05-18). Currently mixes orchestration with quality summary and worker glue (split task `PLAN-split-pipeline.py` pending). |
| `ocr.py` | OCR entry point. Routes to native PDF text extraction, page-level OCR cache, or HTTP sidecar. |
| `ocr_engine/` | Pluggable OCR engines and canonical merge. Each engine emits `IntelligentOcrBlock`s; `canonicalize.py` merges multi-engine candidates into canonical reading order. |
| `ocr_engine/engines/` | One file per engine: PaddleOCR-VL, PP-StructureV3, PP-OCRv5 DirectML, PP-OCRv5 Paddle, OpenAI vision, HTTP DocumentAI sidecar, Docling, hybrid pipeline. |
| `layout_normalizer.py` | Profile-driven post-OCR cleanup. Same-line merge, paragraph reflow, screen-chrome removal, patient-header detection, `key_value` derivation. |
| `deidentify.py` | PHI redaction using `DocumentProfile.phi_patterns` plus inline label rules. Emits the de-identified `DocumentIR` that downstream layers consume. |
| `document_context.py` | Builds the page-level `DocumentContext` with materialized page images and per-page tables. Local-only by default. |
| `evidence.py` | Heuristic evidence retrieval. FTS-style scoring over de-identified blocks, group context window, evidence pack hashing. |
| `evidence_first.py` | Evidence-first extraction core: local rule-driven evidence, field policy adjudication (PASS / REVIEW / MISSING / CONFLICT), conversion to `ExtractionCandidate`. |
| `llm_provider/` | LLM router, protocol adapters (OpenAI Responses, OpenAI-compatible chat, Anthropic, Gemini), local conservative fallback, JSON-schema parsing, response cache. |
| `model_providers.py`, `model_profiles.yaml` loader, `model_selection.py`, `model_auth.py` | Provider catalog, active model profile, API key cooldown and storage policy. |
| `validation.py`, `rules.py` | Guardrails after LLM/local extraction: evidence-grounding check, allowed-code check, conflict policy. |
| `review.py` | Manual review state transitions, immutable `review_audit` rows. |
| `export.py` | Excel export with main sheet + evidence audit sheet, gated by `ExportGateConfig`. |
| `diagnostics.py`, `observability.py` | Read side of the processing ledger; stage and model-call summaries for the diagnostics UI. |
| `runtime_status.py`, `safe_errors.py`, `secret_store.py`, `ocr_accelerators.py`, `source_ocr.py`, `source_pages.py` | Service plumbing: GPU probe, error redaction, OS-keychain credential storage, source-page image cache. |

## Boundary Contracts

These are the contracts crossed by every case. Changing any of them is a contract change and goes through `docs/DECISIONS.md`.

### DocumentIR

`DocumentIR` is the canonical layout-normalized, de-identified document representation. It is the only document shape that downstream extraction and remote LLM calls may consume.

- `DocumentIR.blocks: list[DocumentIRBlock]` carries `block_id`, `page`, `reading_order`, `text`, `bbox`, `block_type`, `section_id`, `section_label`, `document_kind`, `document_region`, `key_label`, `value_text`, `parent_block_id`, `derived_from_block_ids`, table coordinates (`table_id`, `row`, `col`, `row_span`, `col_span`), engine provenance, and merge metadata.
- The pipeline keeps two snapshots:
  - `cases.raw_document_ir_json`: the protected raw OCR snapshot, before redaction. Never sent to remote LLMs. Used for forensic review only.
  - `cases.document_ir_json`: the de-identified, layout-normalized version that downstream stages consume.
- `DocumentIR.metadata` carries `ocr_engine`, `ocr_profile`, `pipeline_stages`, `canonical_blocks_version` (for example `ocr-canonical-layout-v3`), `layout_normalization`, `deidentification`, OCR cache status, page quality, page images.

### DocumentContext

`DocumentContext` is the page-organized view used by evidence collection and remote-safe payloads.

- `DocumentContextPage` carries blocks in reading order, per-page tables, an optional `DocumentPageImage`, and a quality dict.
- Online exposure is gated by `ExtractionSchema.remote_exposure_policy`. Defaults for medical inpatient: `allow_full_document_context=False`, `allow_page_images=False`, `allow_raw_block_text=False`, `allow_safe_evidence_candidates=True`. Online evidence collection therefore receives a redacted summary, not the full transcript or images.

### EvidenceCandidate

Produced by both the local rule layer (`evidence_first.collect_local_evidence`) and the LLM evidence-collection stage. Each candidate must reference a real `block_id` and copy a verbatim `evidence_text` span. Forbidden inference paths (family context, diagnosis-derived gender, signature region) are tagged with `forbidden_inference_flags`; adjudication rejects candidates that carry such flags.

### FieldDecision

Output of `evidence_first.adjudicate_field_decisions`. Status set is fixed: `PASS`, `REVIEW`, `MISSING`, `CONFLICT`. `selected_candidate` (if any) drives the downstream `ExtractionCandidate`. `pass_reasons` and `review_reasons` are recorded for audit.

### ExtractionCandidate / ValidatedFieldResult

`ExtractionCandidate` is the merged result of LLM + adjudication. After `validation.py` checks evidence grounding, allowed codes, and policy, it becomes `ValidatedFieldResult` with `auto_accepted: bool`. Only auto-accepted or human-reviewed results flow into export.

## Data Flow Detail

1. **Upload** (`POST /api/cases`): file is saved to `var/storage/uploads/<case_id>/`. A `CaseRecord` row is created with status `queued`.
2. **Enqueue** (`pipeline.enqueue_case`): a thread-pool worker picks the case and calls `process_case`. `case_workers` and `max_pending_cases` are configurable. On process restart, in-flight runs are still recorded in `processing_runs` but recovery is a tracked PLAN task; for now, restart can leave a case stuck in `extracting` / `ocr`.
3. **OCR** (`ocr.build_document_ir`): chooses route via `config/ocr_profiles/*.yaml`. Native PDF text bypasses OCR. Image and image-PDF pages go through the sidecar (`EYEX_OCR_DOCUMENT_AI_URL`) which orchestrates PP-StructureV3 layout, PP-OCRv5 DirectML lines, optional PaddleOCR-VL. Backend canonicalizes multi-engine output. OCR cache is keyed by file SHA-256, page index, render DPI, preprocess profile, and merge policy version.
4. **Layout normalization** (`layout_normalizer.normalize_document_layout`): applies the active `DocumentProfile`. Removes screen chrome, merges same-line fragments, reflows wrapped paragraphs, classifies blocks into regions (`patient_header`, `clinical_body`, `signature`, etc.), derives `layout_key_value` blocks for split label/value pairs.
5. **De-identification** (`deidentify.deidentify_document_ir`): applies inline label redaction, configured PHI patterns, and the `blocks_online_llm` flag for sensitive matches. The de-identified `DocumentIR` is stored on the case and is the only version that crosses the remote boundary.
6. **DocumentContext build** (`document_context.build_document_context`): organizes the de-identified DocumentIR by page. Page images are materialized only when the active schema permits remote vision and the case is so configured.
7. **Evidence collection** (`evidence_first.collect_local_evidence` and provider `collect_evidence`): rule-driven local candidates (regex, fact-then-code, score derivation, implicit negative) plus, when allowed, LLM-collected candidates. Candidates carry `block_id`, page, bbox, source priority, and `forbidden_inference_flags`.
8. **Adjudication** (`evidence_first.adjudicate_field_decisions`): per field, applies `FieldEvidencePolicy`. Multiple non-`unknown` codes with `conflict_policy=review_conflict` produce `CONFLICT`. No usable candidate produces `MISSING`. Otherwise the highest-priority candidate becomes the selected result and is checked against pass criteria.
9. **Verification** (`provider.verify_against_document`): re-checks that selected evidence text appears verbatim in a referenced DocumentIR block. Mismatches are downgraded to `REVIEW` with explicit reasons.
10. **Validation guardrails** (`validation.validate_candidate`): allowed-code list, evidence span grounding, evidence-policy compliance. Sets `validation_state` and `auto_accepted`.
11. **Persistence**: `field_results` rows replace any prior results. `processing_runs` is finalized with quality summary. `model_calls` carry per-stage provider, route, tokens, cache status, fallback attempts.
12. **Manual review** (`PATCH /api/cases/{id}/review/{field}`): writes a `review_audit` row (immutable). Manual non-`unknown` overrides without document-grounded evidence carry `acceptance_reason=manual_review` and `manual_review_without_document_evidence` for traceability.
13. **Export** (`GET /api/cases/{id}/export`): Excel main sheet + Evidence Audit sheet, gated by `ExportGateConfig.require_pass_or_reviewed`. Unknown values are written as `unknown` literal (medical template), not numeric `9`.

## Configuration as Product Behavior

Config under `config/` is treated as product behavior. The runtime reads YAML through `core/config_loader.py`. Available config kinds:

| Kind | Path | Owns |
| --- | --- | --- |
| `document_profiles` | `config/document_profiles/*.yaml` | Section aliases, document-kind rules, PHI labels and patterns, layout normalization rules, default extraction system prompt and rules, OCR vision prompt. |
| `extraction_schemas` | `config/extraction_schemas/*.yaml` | Field groups, fields, allowed codes, evidence priority, evidence policy, rule patterns, pre-redaction derivations, remote exposure policy, semantic strategy. |
| `export_templates` | `config/export_templates/*.yaml` | Export columns, headers, unknown mapping, export gate. |
| `ocr_profiles` | `config/ocr_profiles/*.yaml` | OCR pipeline stages, page router, engine list, accelerator policy, render DPI, cache policy, merge policy version, GPU policy. |
| `model_profiles` | `config/model_profiles/*.yaml` | LLM provider, model id, base URL, auth env vars, response format, reasoning effort, fallback chain, context window, cost. |
| `model_providers` | `config/model_providers/*.yaml` | Provider catalog: protocol, default base URL, auth schema, model discovery, capabilities, default fallback. |
| `evaluation_profiles` | `config/evaluation_profiles/*.yaml` | Field extraction eval gold cases, field tags, thresholds, token budget. |
| `ocr_evaluation_profiles` | `config/ocr_evaluation_profiles/*.yaml` | OCR regression cases with truth pages, blocks, tables. Real-hardware profiles require de-identified corpus before they can pass. |
| `validation_rules` | `config/validation_rules/*.yaml` | Clinical guardrail descriptions surfaced through `/api/config`. |

Domain-level extension is config-first. `services/domain_profile.py` reads the active `DocumentProfile`; new domains add a profile, schema, export template, and (if needed) layout/PHI overrides. Pipeline code stays domain-agnostic.

## OCR Routing

OCR routing is profile-driven, governed by `config/ocr_profiles/*.yaml`. There are no runtime engine override environment variables.

- The active profile (default: `windows_radeon_balanced`) declares pipeline stages, page-kind router, engines, render DPI, and cache policy.
- The page router maps `page_kinds` (native_pdf_text, image, image_ocr, image_pdf_ocr, scan, screenshot, table, complex_layout) to engine ids.
- `ocr_engine/canonicalize.py` merges raw multi-engine candidates into canonical reading order. Coordinate system is `source_page_pixels`.
- `merge_policy_version` is part of the OCR cache key; bumping it invalidates caches automatically.
- The current target boundary (tracked split task in `PLAN.md`) is: OCR engines and canonical merge stay in `ocr_engine/`; profile-driven post-OCR layout work (same-line merge, paragraph reflow, screen chrome removal, patient header detection, key-value derivation) belongs to `layout_normalizer.py`. New code must respect this boundary; existing overlap inside `canonicalize.py` is the next split target.

## LLM Routing

Business pipelines never import a protocol adapter directly. They go through `services/llm_provider/`:

- `types.py`: `SemanticExtractionProvider` interface — `extract_group`, `collect_evidence`, `adjudicate_fields`, `verify_against_document`.
- `adapters/`: protocol-specific implementations. `openai_compatible.py` (OpenAI-compatible chat: DeepSeek, OpenRouter, Moonshot, Qwen, Z.AI, Azure, custom), `openai_responses.py` (OpenAI Responses), `anthropic.py`, `gemini.py`. Structured output capability detection and async mixin live in private modules (`_structured_output.py`, `_openai_compatible_async.py`).
- `fallback.py`: the `ModelFallbackProvider` walks the active `ModelProfile.fallbacks` chain. Permanent errors are not retried. Rate limit and timeout trigger short cooldown on the API key (per `model_key_cooldown_seconds`).
- `payloads.py`: builds the request payload for each protocol. Evidence-first system prompt is composed from `extraction_system_prompt(document_profile)` plus a fixed evidence-collection rules block. The Responses input is a JSON object with `task`, `remote_context_mode`, `remote_exposure_policy`, `rules`, `document_context`, `fields`, and `output_schema`.
- `parsing.py`: response JSON schemas (`_response_schema`, `_evidence_candidate_response_schema`) and tolerant JSON object parsing with cache hooks.
- `cache.py`: request-level cache keyed by schema id, prompt template, model, and evidence hash. Cache hits skip the call.
- `local_extraction.py`: the `ConservativeLocalProvider` returns explicit-evidence-only candidates when remote LLM is unavailable or disallowed. Complex fields stay `unknown + review_required`.

## Observability Ledger

Three tables, all linked by `case_id` and `run_id`, form the durable trace.

- `processing_runs`: one row per `process_case` attempt. Stores config snapshot, quality summary, page count, OCR block count, result counts, error code/message, started/completed timestamps, total duration.
- `processing_events`: per-step rows recording `step_name`, `status`, `payload`, error code/message, started/completed timestamps. Steps include `load_upload`, `ocr_document_ir`, `normalize_document_layout`, `deidentify_document_ir`, `extract_document` (with sub-steps `build_document_context`, `collect_evidence`, `adjudicate_fields`, `verify_against_document`, `candidate_conversion`), `persist_results`.
- `model_calls`: per-LLM-call rows recording stage, provider, model, mode, fields, input/cached/output tokens, cost, fallback attempts, cache status, error.

Diagnostics UI reads these tables; it never reconstructs a single in-memory snapshot. Schema changes are observability contract changes and must go through `docs/DECISIONS.md`.

## Privacy Boundary

- Original uploads stay under `var/storage/uploads/`.
- Raw `DocumentIR` (pre-redaction) is stored protected on the case; never crosses to the remote LLM, evidence UI, or export. It exists so a reviewer can audit redaction quality.
- De-identified `DocumentIR` is the only document representation that downstream evidence and LLM stages may use.
- `RemoteExposurePolicy` on the active extraction schema gates remote upload of full document context, raw block text, and page images. Medical inpatient default forbids all three.
- Address-derived fields use safe local derivation (`PreRedactionDerivationRule`); the resulting evidence references a derived block, not the original address.
- API keys are stored OS-protected (DPAPI on Windows, in-memory on others). Plaintext storage requires explicit opt-in (`EYEX_ALLOW_PLAINTEXT_PROVIDER_KEYS=true`).

## Performance and Quality Targets

The following targets come from `AGENTS.md`. They are evidence-driven, not asserted in code.

- Single-page OCR P95 under 12 seconds on the DirectML PP-OCRv5 server route on the reference Radeon RX 6600 workstation. CUDA and ROCm targets get their own baselines once a real corpus is wired in.
- Single-field evidence-first extraction P95 under 6 seconds on the default DeepSeek v4-flash route.
- Any change that degrades a recorded P95 by more than 30% must be flagged with eval evidence.
- Precision targets are tracked through `config/evaluation_profiles/*.yaml` and `config/ocr_evaluation_profiles/*.yaml`. Precision tasks land with before/after numbers per `AGENTS.md` Precision Tasks section.

## Frontend Boundary

- `frontend/src/shared/api/client.ts` is the only HTTP entry point. Other code calls typed wrappers; the governance scan blocks raw `fetch`, `axios`, `XMLHttpRequest`, and hard-coded `/api/` paths elsewhere.
- `frontend/src/shared/api/schemas.ts` is the runtime zod contract. Backend `response_model` and frontend zod must move together.
- Errors are normalized as `ApiError`. Malformed 2xx responses become `ApiError(502)` rather than silent partial state.
- Feature folders under `frontend/src/features/` are vertical slices: `cases/` (queue, evidence panel, source view, transcript), `review/` (field results, review actions), `settings/` (provider settings, system settings), `diagnostics/` (runtime status, processing ledger view), `app/` (top-level shell, case switching).

## Known Boundary Frictions

These are real, currently in `PLAN.md` or `docs/DECISIONS.md`. Listed here so new sessions do not redesign them blind:

- `ocr_engine/canonicalize.py` does some same-line merging that the target boundary places in `layout_normalizer.py`. Tracked as "Clarify ocr_engine vs layout_normalizer boundary" in `PLAN.md`.
- No Alembic baseline yet; database evolves via `Base.metadata.create_all` plus an ad hoc `_ensure_sqlite_columns` shim. Tracked in `PLAN.md`.
- In-memory thread-pool queue with no durable recovery on process restart; in-flight runs can stick in `extracting` / `ocr`. Tracked in `PLAN.md`.
- Further split of `services/llm_provider/` into `protocols/`, `router.py`, `credentials.py` is planned but not done; the registry layer in `services/llm_provider/registry.py` already covers provider dispatch (E1-011 Phase 3, 2026-05-18) but the protocol-vs-router-vs-credentials separation still lives inside `adapters/` and `fallback.py`.

## Decision Anchors

When extending or changing any of the above, anchor to the relevant decision in `docs/DECISIONS.md`. The fast-lookup view is the "Active Index" at the top of that file; the entries below are the most load-bearing for code that crosses the listed boundaries.

- OCR engine order is profile-driven (2026-04-30).
- Evidence-first multimodal extraction is the default medical strategy (2026-04-30).
- Processing observability is a first-class ledger (2026-04-30).
- Remote medical extraction is safe-evidence-only by default (2026-05-01).
- Manual review overrides require auditable provenance (2026-05-01).
- Layout normalization separates raw OCR from extraction IR (2026-05-01).
- OCR overlay and canonical merge are layer-safe (2026-05-05).
- OCR merge policy v2 (now v3) uses visual order before raw reading order (2026-05-05).
- Provider API responses are contract-validated at the frontend boundary (2026-05-05).
- Domain plugin registry stays retired (2026-05-17).
- Governance baseline tightened: complexity ceiling, dependency rules, perf baselines (2026-05-17).
- dev is the default integration target; main is promoted in batches (2026-05-17, supersedes 2026-04-30 GitHub branches entry).
- Default-inheritance shim for `collect_evidence` is forbidden (2026-05-18, E1-011 Phase 1; closed by Phases 2 and 3 the same day).
- Evidence-first prompt promotes field-level policy above generic rules (2026-05-18, `EVIDENCE_FIRST_PROMPT_VERSION = eyex-evidence-first-v2`).
- rule_pre_accepted shortcut bypasses LLM for high-confidence rule_shortcut groups (2026-05-18).
- Documentation maintenance contract (2026-05-18, AGENTS.md "Documentation Maintenance" + DECISIONS.md "Active Index").

When this document and a decision entry disagree, the decision entry wins; this file is updated to match.
