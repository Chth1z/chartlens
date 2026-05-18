# EYEX Decision Log

Use this file only for decisions that affect architecture, data contracts, security/privacy, OCR/LLM behavior, project workflow, or deletion/compatibility policy. Keep entries short.

Every entry carries a `Status:` line with one of:

- `active` — the decision still governs current behavior.
- `superseded by <YYYY-MM-DD title>` — replaced by a later entry; the new entry must be referenced by date and title and must update this entry's Status in the same commit.
- `archived (<reason>, <date>)` — historical only; not enforced today.

The "Active Index" below is the fast-lookup view. Maintain it whenever an entry is added, superseded, or archived (per `AGENTS.md` "Documentation Maintenance").

## Active Index

Listed in reverse chronological order. Click through to the dated heading for the full text.

### Architecture and workflow

- 2026-05-18 — rule_pre_accepted shortcut bypasses LLM for high-confidence rule_shortcut groups
- 2026-05-18 — Evidence-first prompt promotes field-level policy above generic rules (`EVIDENCE_FIRST_PROMPT_VERSION = eyex-evidence-first-v2`)
- 2026-05-17 — Architecture and roadmap formalized (`docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/REFERENCE_PROJECTS.md`)
- 2026-05-17 — Governance foundation refresh (constitution rewrite)
- 2026-05-17 — Governance baseline tightened: complexity ceiling, dependency rules, perf baselines
- 2026-05-17 — Domain plugin registry stays retired (supersedes parts of 2026-04-30 entries)
- 2026-05-17 — dev is the default integration target; main is promoted in batches (supersedes 2026-04-30 GitHub branches entry)
- 2026-04-30 — Personal Codex governance over team process
- 2026-04-30 — Delete stale compatibility by default

### Data contracts and observability

- 2026-04-30 — Processing observability is a first-class database ledger (`processing_runs` / `processing_events` / `model_calls`)
- 2026-05-01 — Manual review overrides are auditable export values
- 2026-05-01 — Case deletion means archive, not purge
- 2026-05-01 — Unknown export code is literal `unknown`
- 2026-05-06 — Source OCR and model schemas preserve table evidence
- 2026-05-05 — Provider API responses are contract-validated at the frontend boundary

### Privacy and remote routing

- 2026-04-30 — Address-derived fields use safe local derivations
- 2026-05-01 — Remote medical extraction is safe-evidence-only by default
- 2026-05-05 — Remote browser access is token-gated and CORS-aligned

### OCR routing and layout

- 2026-04-30 — OCR engine order is profile-driven
- 2026-04-30 — Medical extraction uses evidence-first document context
- 2026-04-30 — Stitch tiled OCR line fragments before evidence display
- 2026-04-30 — Evidence UI folds same-line OCR alternatives
- 2026-04-30 — Screen-capture noise and non-patient context are not evidence
- 2026-05-01 — OCR layout normalization separates raw OCR from extraction IR
- 2026-05-01 — Split header labels are rebuilt locally as key-value evidence
- 2026-05-01 — Medical export requires PASS or manual review
- 2026-05-01 — Source OCR preview uses materialized page images
- 2026-05-01 — Strong OCR is layout-led canonical merging
- 2026-05-01 — Runtime readiness is a backend API contract
- 2026-05-01 — Installer owns Docker Desktop bootstrap
- 2026-05-01 — PaddleOCR-VL is parked outside the default OCR route (supersedes the same-day "Radeon OCR defaults are GPU-guarded" and "PaddleOCR-VL AMD GPU means official ROCm sidecar" entries)
- 2026-05-05 — OCR overlay and canonical merge are layer-safe
- 2026-05-05 — OCR merge policy v2 uses visual order before raw reading order
- 2026-05-05 — Modular OCR engine split (`intelligent_ocr.py` -> `ocr_engine/`)
- 2026-05-05 — Model singleton pool adopted for all OCR engines
- 2026-05-05 — Retry with exponential backoff added to engine orchestration
- 2026-05-05 — Graceful degradation: partial results returned when no engine meets threshold
- 2026-05-05 — MinerU-style bbox containment added to dedup alongside IoU
- 2026-05-05 — OCR engine import order resolves Windows DLL load conflicts (WinError 127)
- 2026-05-05 — Sidecar OCR route is config-only, not env-overridable
- 2026-05-05 — OCR orchestration now enforces timeouts and emits structured traces
- 2026-05-05 — OCR regression profiles are versioned config, not ad hoc notes
- 2026-05-05 — OCR failures and latency must be diagnosable end-to-end
- 2026-05-06 — NVIDIA OCR uses the same canonical layout pipeline as Radeon
- 2026-05-06 — Table cells remain atomic through extraction and export
- 2026-05-06 — Hardware OCR evals are blocked unless real corpus and GPU route exist
- 2026-05-06 — OCR eval reports include hardware readiness evidence
- 2026-05-06 — OCR regression scores layout/table truth, not text alone
- 2026-05-06 — Stale OCR sidecars must fail with restart instructions

### LLM provider routing

- 2026-05-18 — Default-inheritance shim for `collect_evidence` is forbidden (E1-011 Phase 1; closed by Phases 2 and 3)

### Pending decisions

- 2026-05-17 — application/ vs services/ flat layout (`codex/architecture-decision`, blocks pipeline split, provider split, OCR boundary split)

### Promotion records (informational)

- 2026-05-18 — Seventh batched dev to main promotion
- 2026-05-18 — Sixth batched dev to main promotion
- 2026-05-18 — Fifth, Fourth, Third, Second, First batched dev to main promotions

## Template

```markdown
## YYYY-MM-DD - <decision title>

- Decision:
- Why:
- Rejected:
- Status: active
- Revisit when:
```


## 2026-05-17 - Architecture and roadmap formalized

- Decision: Establish three new authoritative docs: `docs/ARCHITECTURE.md` for the pipeline and module layering, `docs/ROADMAP.md` for the phased precision plan (E0 governance prerequisites, E1 borrow-from-open-source improvements, E2 product-grade precision and throughput), and `docs/REFERENCE_PROJECTS.md` for the open-source reference registry with verified licenses. Every roadmap task carries a stable ID and an eval-profile-anchored acceptance line. Reference borrowing defaults to design-only with commit-pinned URLs; source-level reuse goes through an adapter directory plus a license decision in this log.
- Why: The user's directive is precision-driven optimization across OCR, text extraction, and LLM prompts, with traceable code changes. Without a single architecture doc, every session re-derives the pipeline. Without a roadmap that anchors to eval profiles, precision claims are unverifiable. Without a license-checked reference registry, borrowing from PaddleOCR/MinerU/Docling/olmOCR/Marker etc. risks license violation or supply-chain drift. The three docs together turn the AGENTS.md Precision Tasks rule into something operable.
- Rejected: Letting the README plus `docs/DECISIONS.md` continue to carry architecture by accident; writing a single mega-document instead of three focused files; embedding upstream source under `backend/app/` to "borrow" patterns without explicit attribution and license checking.
- Revisit when: A new domain beyond clinical Chinese inpatient lands; a real-hardware medical OCR corpus unblocks `medical_inpatient_zh` eval (E2-001); a roadmap task discharges enough work that the phase boundaries need redrawing.

## 2026-05-17 - Governance foundation refresh

- Decision: Rewrite `AGENTS.md` so every rule describes the current repository, not aspirations. Concrete changes: drop the unimplemented pytest-marker regime; restate the OCR engine vs layout normalizer split as a target boundary with a tracked PLAN task instead of a present fact; align the single-file complexity ceiling with the governance scan as 500-line soft trigger plus 800-line hard warning; add a documentation map that lists `AGENTS.md`, `README.md`, planned `docs/ARCHITECTURE.md`, planned `docs/ROADMAP.md`, planned `docs/REFERENCE_PROJECTS.md`, `docs/DECISIONS.md`, `docs/CODEX_WORKFLOW.md`, and `PLAN.md`; add a Commit Traceability section that requires every commit to carry a `Refs:` task ID and a `Verification:` line; add a Reference Projects Policy that defaults to reference-only borrowing and reserves a gitignored `references/` directory for shallow study clones; add a Precision Tasks section that requires before/after eval evidence for OCR, evidence-grounding, extraction, and prompt changes.
- Why: Several existing rules described mechanisms that did not exist in code (pytest markers, OCR boundary, domain plugin registry), which made the constitution unreliable for new sessions. The user explicitly required traceable commits, source-attributed reference work, and precision-driven optimization, none of which were governed by the previous text.
- Rejected: Quietly relaxing the 500-line ceiling to match the governance scan; keeping marker discipline as a written rule with no enforcement; describing the OCR boundary as already enforced; introducing a heavyweight ADR or PR template just for traceability.
- Revisit when: Marker-based test selection actually lands; `application/` versus `services/` layout decision lands and changes the architecture boundary; a real multi-developer workflow needs full PR review.

## 2026-05-17 - Domain plugin registry stays retired

- Decision: Domain behavior in EYEX is configured exclusively through `config/document_profiles/*.yaml` and `config/extraction_schemas/*.yaml`, read by `backend/app/services/domain_profile.py` and `backend/app/services/layout_normalizer.py`. Identifiers `domain_plugins`, `register_domain_plugin`, and `get_domain_plugin` remain on the governance scan stale-identifier list and must not return. The previous wording in `README.md` and the 2026-04-30 governance entry that suggested registering new plugins for new domains is superseded.
- Why: The plugin registry was never implemented in code; only the documentation referred to it. Keeping aspirational mechanisms in user-facing docs creates drift and lets future sessions accidentally rebuild the wrong abstraction. Profile-driven YAML covers the medical inpatient domain today and is the documented extension path.
- Rejected: Building the runtime plugin registry now to match old documentation; allowing pipeline branches keyed on `profile_id`; documenting both options in parallel.
- Revisit when: A real new domain needs behavior that cannot be expressed through `document_profiles` plus `extraction_schemas` plus existing `services/` modules, and a profile-only solution is shown to be inadequate by an eval profile.## 2026-04-30 - Personal Codex governance over team process

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
- Status: superseded by 2026-05-17 "dev is the default integration target; main is promoted in batches".
- Revisit when: More contributors start changing the repository or the project needs release branches.

## 2026-04-30 - Address-derived fields use safe local derivations

- Decision: Sensitive source text may be used only by local pre-redaction derivation rules. Final extraction evidence must reference a safe derived DocumentIR block, never the original address.
- Why: Chinese medical research fields such as urban/non-urban residence may require address clues, but PHI must not enter online LLM prompts, exports, or user-facing evidence.
- Rejected: Sending redacted addresses to the LLM for inference, storing raw address spans as evidence, and hard-coding medical address rules in the pipeline.
- Revisit when: A privacy-reviewed local geocoder or consented address feature becomes part of the product contract.

## 2026-04-30 - Stitch tiled OCR line fragments before evidence display

- Decision: OCR line fragments from overlapping image tiles are stitched in the OCR de-duplication path and mirrored in the evidence UI for already-processed cases.
- Why: DirectML safe-mode tiling can emit left/right partial text for the same visual line; treating those fragments as separate blocks corrupts paragraph boundaries and review evidence.
- Rejected: Fixing only the class-Word layout or hiding duplicate fragments in the UI without correcting OCR block semantics.
- Revisit when: The OCR engine returns stable full-line polygons without tiled duplicate candidates.

## 2026-04-30 - Evidence UI folds same-line OCR alternatives

- Decision: Same-line OCR candidates with overlapping boxes, fuzzy suffix/prefix overlap, or fuzzy containment are collapsed before class-Word rendering and original-image OCR review; OCR-missing section delimiters are normalized only for configured clinical headings.
- Why: Real scanned cases can produce both a full-line candidate and local duplicates with punctuation, one-character OCR drift, or `l/1` differences, which otherwise duplicates paragraphs and breaks section boundaries even when the OCR recognized the page.
- Rejected: Asking the model to repair duplicated paragraphs, deleting all overlapping boxes blindly, globally deleting checkbox-like OCR symbols from backend output, and treating the source-image OCR view as image-only without readable converted text.
- Revisit when: The OCR pipeline stores ranked line alternatives explicitly instead of emitting duplicate primary blocks.

## 2026-04-30 - Medical extraction uses evidence-first document context

- Decision: Chinese medical extraction defaults to `evidence_first_multimodal`: build a full-page `DocumentContext`, collect field evidence candidates, adjudicate with field policies, validate evidence grounding, and leave missing fields for review instead of calling the old group evidence-pack fallback.
- Why: Local section cropping and field-level evidence packs lose page context, table structure, OCR alternatives, and counter-evidence; medical extraction needs traceable field evidence and conflict handling more than token minimization.
- Rejected: Sending one flat OCR transcript to the model for direct answers, letting model confidence decide auto-fill, and adding field-specific hard-coded fixes for sex/history errors.
- Revisit when: The evidence-first eval set shows a field category that consistently needs a new first-class evidence strategy rather than fallback to old group prompts.

## 2026-04-30 - Processing observability is a first-class database ledger

- Decision: Every processing attempt writes a durable `processing_runs` record with child `processing_events` and `model_calls`, all tied to `case_id` and `run_id`; diagnostics read historical runs from the ledger instead of reconstructing a single latest snapshot.
- Why: Codex needs stable, queryable runtime evidence to debug regressions, compare reprocess attempts, isolate slow stages, and choose whether the next fix belongs in OCR, evidence collection, model routing, or validation.
- Rejected: Relying on stdout access logs, overwriting `diagnostics_json` as the only run record, storing raw secrets or unsafe tracebacks in ordinary diagnostics, and keeping the old evidence-pack fallback inside the evidence-first path.
- Revisit when: Multi-user retention policy requires purging or encrypting per-run event payloads beyond the existing protected raw DocumentIR.

## 2026-04-30 - Screen-capture noise and non-patient context are not evidence

- Decision: Chinese medical OCR prompts and evidence policy ignore Word rulers, window tabs, toolbars, taskbars, stickers, monitor edges, and untrusted system chrome; family, maternal pregnancy, spouse, and children context cannot produce patient positive or negative history decisions.
- Why: Real cases are often photographed from hospital systems, and those images contain repeated headers, UI metadata, signatures, and family-history sentences that can look like valid field evidence after OCR linearization.
- Rejected: Treating every visible string in a screen photo as clinical evidence, and using broad negative phrases in family or pregnancy context as patient history.
- Revisit when: The document context model has explicit trusted/non-trusted region labels from layout analysis and an eval set proves those regions are reliable.

## 2026-05-01 - Manual review overrides are auditable export values

- Decision: A human reviewer may confirm a non-`unknown` value without a grounded DocumentIR evidence span only through the manual review endpoint; the result is marked `reviewed`, keeps `acceptance_reason=manual_review`, records `manual_review_without_document_evidence` in provenance and validator messages, and writes an immutable `review_audit` before/after record.
- Why: Some fields can be known to the reviewer even when OCR/evidence collection failed. Blocking those reviews prevents the local workflow and Excel export from completing, but silently treating them as model evidence would violate traceability.
- Rejected: Allowing the extraction pipeline to emit non-`unknown` values without grounded evidence, faking evidence spans, and exporting manually-entered values without an audit row.
- Revisit when: The UI supports selecting or drawing a source evidence region for every manual override, so manual values can be grounded to DocumentIR or image coordinates by default.

## 2026-05-01 - Remote medical extraction is safe-evidence-only by default

- Decision: `medical_inpatient_zh` forbids remote upload of full `DocumentContext`, raw OCR block text, and page images by default. Online evidence collection must fall back to local evidence generation unless a versioned schema explicitly enables full context exposure.
- Why: Real medical records contain sensitive health and identity data. Evidence-first extraction still needs optional model routing, but the default boundary must prevent whole-document OCR or original images from leaving the local machine.
- Rejected: Sending the entire OCR transcript to a cheap online model, relying on model prompts alone to avoid PHI use, and hiding the upload policy inside provider code instead of schema configuration.
- Revisit when: There is a reviewed deployment profile with consent, data-processing agreements, retention controls, and an eval showing that remote full-context evidence collection is required for an accepted field category.

## 2026-05-01 - Case deletion means archive, not purge

- Decision: Frontend delete removes a case from the active list by setting `status=archived`; original uploads, extracted results, manual review audit rows, processing runs, model calls, and vision fallback requests remain in the database/storage for traceability.
- Why: Codex debugging and clinical review both need the full chain of custody after an operator hides a case from daily work.
- Rejected: Physical deletion from the case row cascade and deleting the upload directory through the UI delete action.
- Revisit when: A separate retention/purge workflow with explicit confirmation and exportable audit evidence is added.

## 2026-05-01 - Unknown export code is literal `unknown`

- Decision: Medical export templates write missing/indeterminate coded fields as `unknown`, not numeric `9`.
- Why: Several research fields may legitimately contain numeric values, so encoding unknown as `9` can be confused with real field values during analysis.
- Rejected: Keeping the historical code-9 convention in headers or per-column unknown mappings.
- Revisit when: A downstream registry contract requires numeric unknown codes and has field-level collision rules.

## 2026-05-01 - OCR layout normalization separates raw OCR from extraction IR

- Decision: Case processing preserves the raw OCR `DocumentIR` in protected storage, then applies profile-driven layout normalization before de-identification and extraction. The normalizer removes configured screen chrome, rebuilds reading order, merges same-line fragments, detects patient headers, marks document regions, and carries clinical sections across pages. It also derives local `layout_key_value` blocks from configured labels such as `姓名`, `性别`, `年龄`, `床号`, `病案号`, and operation-note metadata; derived sensitive values are de-identified together with the derived block text before extraction or remote evidence use. Field evidence policies may reject candidates from non-patient regions such as signatures and footers.
- Why: Screen-captured Chinese cases have semi-fixed page templates but flexible narrative content. Extraction needs a stable local text/layout layer without sending full records to remote models or hard-coding individual medical fields.
- Rejected: Directly uploading full OCR text for model repair, field-specific post-hoc fixes for sex/history errors, and treating hospital system chrome as clinical evidence.
- Revisit when: The OCR/layout engine emits trusted region classes and table cells with enough accuracy to replace these profile-level normalization rules.

## 2026-05-01 - Split header labels are rebuilt locally as key-value evidence

- Decision: Layout normalization may mark same-line patient header fragments as one trusted header row and derive `layout_key_value` evidence from adjacent configured labels and values, even when OCR split labels such as `性别：` and values such as `男` into separate blocks. The join is bounded by same-line tolerance, configured source regions, configured labels, and a maximum horizontal gap.
- Why: Real Chinese EMR screenshots often have fixed header rows, but OCR engines can split label and value into separate fragments. Mature document pipelines solve this with local reading-order/layout/key-value reconstruction before field extraction; doing it locally improves auto-pass precision without adding human review or uploading full records.
- Rejected: Adding field-specific gender/age fixes, asking users to review every split header field, and sending full OCR text or original screenshots to a remote model for repair.
- Revisit when: Native OCR/table engines provide reliable keyed header cells with bbox and confidence for these EMR templates.

## 2026-05-01 - Medical export requires PASS or manual review

- Decision: Medical export templates may require non-`unknown` values to be either evidence-first `PASS` decisions or auditable manual review overrides. `medical_inpatient_zh` enables this gate, and the Evidence Audit sheet records `exportable` plus `export_gate_reason` for every field result.
- Why: A non-review model result with high confidence is not enough for medical export. The export boundary must enforce the local evidence ledger and keep blocked candidates visible for audit.
- Rejected: Treating model confidence, `review_required=false`, or any non-`unknown` normalized code as sufficient for Excel export.
- Revisit when: Additional export templates need different downstream acceptance contracts, such as numeric unknown codes or explicit reviewer signatures per field.

## 2026-05-01 - Radeon OCR defaults are GPU-guarded, not CPU-heavy

- Decision: `windows_radeon_balanced` requires local PP-OCRv5 server ONNX on DirectML and treats PaddleOCR-VL as an optional remote AMD/ROCm sidecar stage through `EYEX_OCR_PADDLEOCR_VL_URL`. The no-argument installer and probe read that URL from project `.env`; DirectML runtime failures are surfaced in health diagnostics. Local CPU PaddleOCR-VL, PP-StructureV3, and Docling are not default runtime stages or DirectML install warmups.
- Why: On RX 6600-class Windows machines, PP-OCRv5 can run through ONNX Runtime DirectML, but local PaddleOCR-VL/Structure/Docling load CPU-heavy model stacks and can exhaust memory. Accuracy should improve through GPU paths, not by silently falling back to CPU stages that freeze the workstation.
- Rejected: Running PaddleOCR-VL locally on CPU when AMD GPU execution is unavailable, using the backend-to-local-sidecar `EYEX_OCR_DOCUMENT_AI_URL` as the remote VL URL, and making PP-OCRv5 fall back to CPU Paddle when DirectML is missing.
- Status: superseded by 2026-05-01 "PaddleOCR-VL is parked outside the default OCR route".
- Revisit when: A tested local AMD GPU backend for PaddleOCR-VL is available on the target Radeon stack, or the user provisions a stable ROCm host that can run the VL sidecar continuously.

## 2026-05-01 - PaddleOCR-VL AMD GPU means official ROCm sidecar, not local CPU fallback

- Decision: The installer now automatically probes and prepares a project-local official AMD GPU PaddleOCR-VL Docker sidecar using the official `latest-amd-gpu` PaddleOCR images, writing only under `var/`. EYEX consumes both its own `/extract` sidecar shape and the official PaddleOCR-VL `/layout-parsing` API. The `rocm_remote_vl` profile is remote-only and has no local CPU heavy fallbacks.
- Why: PaddleOCR documents AMD GPU support through Docker/ROCm services, while the target RX 6600 Windows setup lacks a ready local ROCm/Paddle runtime. Keeping the VL path sidecar-only prevents another memory-saturating CPU run and gives a concrete GPU route when Docker/ROCm is available.
- Rejected: Asking the user to manually wire the official service URL, using the local `EYEX_OCR_DOCUMENT_AI_URL` as a hidden VL proxy, and retaining CPU PaddleOCR-VL/PP-StructureV3/Docling fallback engines in the ROCm profile.
- Status: superseded by 2026-05-01 "PaddleOCR-VL is parked outside the default OCR route".
- Revisit when: Docker/ROCm is installed and a real PaddleOCR-VL sidecar health check and OCR eval run are available on the target machine.

## 2026-05-01 - Source OCR preview uses materialized page images

- Decision: Original-image OCR review uses project-local materialized page images under `var/storage/source_pages`, keyed by case, page, file hash, and OCR page DPI. The API serves cached page images first and renders missing PDF pages at the per-page OCR DPI, not at a stale document-level DPI.
- Why: Overlay drift and repeated "original preview unavailable" failures came from a brittle contract: the frontend inferred coordinates from live image loading while the backend rendered PDFs on demand from the original upload and could use a different DPI than the OCR blocks. A stable page-image contract keeps the preview, bbox space, and OCR evidence tied to the same page geometry.
- Rejected: Retrying the frontend image tag indefinitely, hiding coordinate boxes when previews fail, relying on document-level `render_dpi` when block-level OCR DPI exists, and serving only transient in-memory rendered PNG responses.
- Revisit when: OCR stores a first-class page raster manifest in `DocumentIR.pages` and the frontend can consume signed local asset references directly.

## 2026-05-01 - Strong OCR is layout-led canonical merging

- Decision: The default Radeon OCR profile is a fixed strong pipeline: PaddleOCR-VL provides primary document layout, PP-StructureV3 provides layout/table/read-order structure, and PP-OCRv5 DirectML provides line/cell text candidates. `DocumentIR.blocks` contains only backend canonical blocks; raw stage output is kept in `raw_candidates`/`candidate_sets` and suppressed candidate audit metadata.
- Why: The observed failures were caused by raw OCR candidates and unreliable stage reading order leaking into final text, producing repeated boxes, page-number boxes, and cross-section reorderings even when the source image text was visible. Layout-led canonical merging keeps bbox coordinates in one source-page coordinate system and makes candidate conflicts auditable without corrupting evidence/LLM input.
- Rejected: Letting PP-OCRv5 raw line order become final document text, silently falling back to PP-OCR-only production output when VL/Structure are unavailable, and fixing visual drift only in the frontend overlay.
- Revisit when: A validated OCR engine emits trusted canonical DocumentIR with table cells, layout regions, and stable reading order at equal or better eval scores than the current canonical merger.

## 2026-05-01 - Runtime readiness is a backend API contract

- Decision: `/api/settings/runtime` reports backend, frontend, and OCR service readiness, including OCR sidecar health, strong pipeline stage checks, actionable repair commands, and current profile metadata. Frontend status cards must consume this backend readiness instead of inferring OCR state only from the last failed processing run. Public local operations are reduced to `install-ocr.cmd`, `start.cmd`, and `stop.cmd`; sidecar-specific scripts are not user-facing commands.
- Why: After reboot, the backend can be reachable while OCR sidecar or PaddleOCR-VL/Structure/DirectML stages are not. The operator needs a precise service-level diagnosis before uploading or reprocessing a case.
- Rejected: Keeping startup state only in console logs, showing "缺失 0 / 尝试 1" when the real failure is sidecar/stage readiness, making each frontend card re-interpret low-level OCR error strings independently, and asking users to manually chain internal `scripts\...` commands.
- Revisit when: EYEX gains a supervised process manager that can expose first-class service lifecycle events without polling `/health`.

## 2026-05-01 - Installer owns Docker Desktop bootstrap

- Decision: `install-ocr.cmd` automatically downloads the official Docker Desktop installer into `var\cache\docker`, runs a project-local elevated Docker install helper, repairs stale partial Docker Desktop ProgramData state when it blocks installation, installs/starts Docker Desktop with the WSL2 backend, waits for the Docker engine, and then starts the optional official AMD/ROCm PaddleOCR-VL compose sidecar. Root `.cmd` wrappers pause before closing unless another EYEX script sets `EYEX_NO_PAUSE=1`.
- Why: OCR setup must remain one-click after reboot or on a clean Windows workstation. Missing Docker should not send the operator into a manual side path, and installer/startup failures must remain visible in the console.
- Rejected: Keeping Docker as a manual prerequisite, printing internal setup commands in the frontend, and allowing double-clicked `.cmd` windows to close before the error can be read.
- Revisit when: EYEX adopts a real Windows service/process manager or a packaged installer that can declare Docker/WSL as managed prerequisites.

## 2026-05-01 - PaddleOCR-VL is parked outside the default OCR route

- Decision: This supersedes the Docker/ROCm PaddleOCR-VL bootstrap decision above. `install-ocr.cmd`, `start.cmd`, runtime readiness, and the default `windows_radeon_balanced` profile no longer prepare, start, or require PaddleOCR-VL. The installer ignores `-RemoteRocmSidecarUrl`, clears `EYEX_OCR_PADDLEOCR_VL_URL`, and uses the local PP-OCRv5 DirectML route plus PP-StructureV3 when available.
- Why: On the target RX 6600 Windows workstation, the official Docker/ROCm route pulled very large images and failed at the local device layer, while local CPU PaddleOCR-VL can exhaust memory. Rebuilding PaddleOCR-VL on DirectML would require owning tokenizer, image preprocessing, generation, postprocessing, bbox recovery, and Markdown/layout reconstruction, which is too risky for the default OCR path.
- Rejected: Default Docker Desktop installation, default ROCm/VL compose startup, local CPU PaddleOCR-VL fallback, and ZLUDA/hand-rolled ONNX PaddleOCR-VL as a production shortcut.
- Revisit when: A supported ROCm host or maintained Windows GPU PaddleOCR-VL adapter is available and passes EYEX OCR evals without breaking the one-click local installer.

## 2026-05-05 - OCR overlay and canonical merge are layer-safe

- Decision: Source-image OCR review may suppress duplicate or obviously bad raw candidates, but it must not invent a wide union bbox for distant same-line fields. Backend layout normalization may join a field label to its adjacent value, but it must not merge the next independent label into the same canonical block. Cross-label raw candidates are hidden from the source overlay when individual field boxes are present.
- Why: Mature document parsers keep raw OCR lines, layout/table regions, and canonical reading order as separate layers. The observed `姓名`/`现住址` connection and overlapping source boxes came from crossing that boundary: display cleanup and same-line normalization were allowed to combine independent fields.
- Rejected: Treating the long connected boxes as a CSS-only issue, merging by text similarity without bbox geometry, and relying on a later LLM/evidence step to repair broken OCR reading order.
- Revisit when: The OCR sidecar emits trusted layout regions and keyed form cells that make these local split/merge guards redundant.

## 2026-05-05 - OCR merge policy v2 uses visual order before raw reading order

- Decision: OCR merge policy `ocr-canonical-layout-v2` treats bbox geometry as the final ordering guard for OCR source text and transcript preparation. Raw engine `reading_order` is only a fallback when no usable bbox exists. Same-line OCR stitching may merge left-to-right suffix/prefix or near-duplicate alternatives, but it must not run reverse text-overlap synthesis that can create right-half-before-left-half lines from tiled OCR output.
- Why: The repeated misordered text issue was reproduced from OCR cache where the right-side tile fragment had a lower raw `reading_order` than the left-side fragment on the same visual line. PP-StructureV3, Docling, MinerU, and LayoutParser-style pipelines all separate layout/coordinates from OCR candidates; EYEX must follow that boundary instead of trusting raw OCR order.
- Rejected: Clearing the frontend symptom only, keeping the v1 cache key, and letting fuzzy overlap rules invent a line that contradicts page geometry.
- Revisit when: The OCR sidecar emits validated canonical line groups with stable reading order and enough debug artifacts to retire the local visual-order guard.

## 2026-05-05 - Modular OCR engine split (`intelligent_ocr.py` → `ocr_engine/`)

- Decision: Split the 2454-line monolithic `intelligent_ocr.py` into a modular `app/services/ocr_engine/` package with 8 submodules: `types`, `errors`, `bbox_utils`, `preprocessing`, `postprocessing`, `payload_parse`, `engine_base`, `canonicalize`, plus `engines/` subpackage with one module per engine. The original bridge has since been deleted after all in-repo callers migrated to canonical imports.
- Why: The monolith violated single-responsibility, made engine-level testing and feature iteration expensive, and blocked image preprocessing enhancements (deskew, CLAHE, adaptive binarize) and structured error codes (DirectML auto-recovery with cooldown). Mature OCR projects (Surya, MinerU, PaddleOCR) use modular package structures.
- Rejected: In-place refactor of the monolith (too risky without regression suite), full re-import migration of all callers in one pass (high blast radius).
- Revisit when: An external package or documented integration requires a compatibility namespace; if that happens, add an explicit deprecated namespace with a dated deletion condition instead of recreating the old service file.

## 2026-05-05 - Remote browser access is token-gated and CORS-aligned

- Decision: Local remote-browser access is allowed only when `EYEX_ALLOW_REMOTE_ACCESS=true` and `EYEX_LOCAL_API_TOKEN` are both set. In that mode, backend request guards and CORS allow remote browser origins so LAN clients can use the app with an explicit bearer token. Browser clients still need the token; loopback stays the default.
- Why: The README promised token-gated LAN access, but the backend originally blocked non-loopback browser origins at the CORS layer. Aligning the CORS policy with the request guard keeps the loopback default intact while making the documented remote mode actually work.
- Rejected: Opening CORS broadly without auth, keeping remote access looped only through non-browser clients, and adding a separate compatibility flag just for browser origins.
- Revisit when: EYEX grows a formal deployment profile for remote access with origin allowlists, reverse proxy guidance, or a stronger auth model.

## 2026-05-05 - Provider API responses are contract-validated at the frontend boundary

- Decision: Frontend provider calls validate `model-providers` payloads at runtime and throw `ApiError(502)` on malformed 2xx responses instead of treating them as success. Provider update, fetch, and activation responses are modeled explicitly rather than `unknown`.
- Why: Mature API clients fail fast on contract breaks and do not silently render or persist malformed provider state. This makes backend/frontend drift visible in tests and in the UI instead of hiding it behind loose typing.
- Rejected: Leaving provider payloads as `unknown`, assuming 2xx always means valid data, or translating contract errors into success states.
- Revisit when: The provider API becomes stable enough for generated client types and schema-driven validation across the whole frontend API surface.

## 2026-05-05 - Model singleton pool adopted for all OCR engines

- Decision: All OCR model instances (RapidOCR/ONNX, PaddleOCR v5, PP-StructureV3) are cached per-process via `ocr_engine/model_pool.py`. Models are loaded once, optionally warmed up, and reused for every subsequent `extract()` call. Config changes (detected via hash) trigger automatic eviction and reload.
- Why: PaddleOCR init takes 2-5s; ONNX/DirectML compilation takes 1-3s. In production, a document processing queue would re-pay this cost on every request without the pool. Aligned with GOT-OCR, Surya, and MinerU singleton patterns.
- Rejected: Per-request model instantiation (existing behavior), global module-level variables (not evictable), class-level cached instances on the engine class (not thread-safe across pool key variants).
- Revisit when: Memory constraints on the sidecar host require explicit model eviction policies or LRU limits.

## 2026-05-05 - Retry with exponential backoff added to engine orchestration

- Decision: The `extract_with_intelligent_ocr` orchestrator now wraps each engine call with `retry_with_backoff()` (max 2 retries, base 1s, max 8s, ±50% jitter). Error classification via `OcrErrorCode.classify()` distinguishes retryable (DirectML crash, timeout, network) from permanent (invalid input, engine unavailable) errors. Permanent errors skip retry immediately.
- Why: Transient DirectML and ONNX runtime failures on Windows/AMD occur occasionally but are recoverable. Without retry, a single hardware glitch fails the entire document silently. Aligned with GOT-OCR and production OCR best practices.
- Rejected: Unlimited retry (DoS risk), same delay retry (thundering herd), retrying on all errors (wastes time on permanent failures).
- Revisit when: Retry storm is observed in telemetry; at that point add per-document retry budget accounting.

## 2026-05-05 - Graceful degradation: partial results returned when no engine meets threshold

- Decision: When all engines fail to meet the quality threshold (`ocr_intelligent_min_chars`, `ocr_intelligent_min_confidence`), the orchestrator now returns the best partial result (by char_count + avg_confidence) with `ocr_intelligent_status: "degraded"` instead of an empty block list. The degradation reason is recorded in `ocr_degradation_reason` metadata.
- Why: A document with 18 good pages and 2 noisy pages should not fail entirely. Returning partial results with explicit status lets the pipeline proceed to LLM extraction while the review UI can flag the quality issue. Aligned with production OCR best practices for partial result acceptance.
- Rejected: Silently lowering quality thresholds system-wide, returning empty result (current behavior), or triggering a hard failure for below-threshold results.
- Revisit when: The degraded status needs to map to a distinct pipeline status in the case record (e.g., `status: "degraded"` instead of `status: "completed"`).

## 2026-05-05 - MinerU-style bbox containment added to dedup alongside IoU

- Decision: OCR block deduplication now checks both IoU ≥ 0.6 AND containment ratio ≥ 0.85 (one block's area fully inside another). Either condition alone qualifies as a duplicate when text is also equivalent.
- Why: DirectML tiled OCR produces overlapping tiles where the same text appears in a small block (tile boundary) and a large block (full tile). IoU is low due to size difference, so the original IoU-only check misses this case. MinerU uses containment checks for the same reason.
- Rejected: Lowering the IoU threshold globally (increases false positives for genuinely different adjacent text), text-only dedup (fragile for OCR variants).
- Revisit when: Medical forms with intentionally repeated labels in different regions show false-positive dedup.

## 2026-05-05 - OCR engine import order resolves Windows DLL load conflicts (WinError 127)

- Decision: Ensure `import torch` executes before any `paddle` or `paddlex` module is imported within the sidecar process (specifically enforced at the top of `ocr_sidecar/main.py`).
- Why: When `paddle` is imported first on Windows, it loads bundled DLLs (like OpenMP's `libiomp5md.dll` or MSVC runtimes) into the process space. When `torch` is subsequently imported, its transitive dependencies (like `shm.dll`) fail to load because they attempt to link against the already-loaded, incompatible DLLs from paddle, resulting in a cryptic `[WinError 127]` (procedure not found). Forcing `torch` to load first resolves the conflict.
- Rejected: Relying exclusively on `os.add_dll_directory` (fails for transitive dependencies loaded via `LoadLibraryExW` with restricted flags), modifying the global system PATH (brittle and affects other apps), or attempting to deduplicate the bundled DLLs on disk.
- Revisit when: PaddleOCR or PyTorch dependencies are upgraded to versions that either statically link their dependencies or use isolated DLL load paths.

## 2026-05-05 - Sidecar OCR route is config-only, not env-overridable

- Decision: The OCR sidecar no longer reads `EYEX_OCR_SIDECAR_ENGINES`, and the installer removes that stale key from `.env` instead of keeping an empty placeholder. Sidecar engine order now comes only from `config/ocr_profiles/*.yaml`.
- Why: Mature document parsers such as Surya, MinerU, Docling, and PaddleOCR separate engine capability selection from runtime process flags. EYEX already declared profile-driven OCR routing as the product contract, but the hidden sidecar env override kept a second conflicting control plane alive.
- Rejected: Keeping a hidden emergency override for local debugging, and clearing the value to empty while still allowing stale `.env` keys to silently reactivate engine drift later.
- Revisit when: EYEX needs a reviewed operational override path with explicit auditability, test coverage, and a rollback story separate from ordinary local `.env` edits.

## 2026-05-05 - OCR orchestration now enforces timeouts and emits structured traces

- Decision: Both backend intelligent OCR orchestration and the local OCR sidecar now wrap each engine attempt with a bounded timeout and emit `ocr_trace` metadata containing per-engine stage status, duration, page metrics, selected engine, and final quality summary. Engine timeouts are classified as `PAGE_TIMEOUT` and fall through to the next engine instead of retrying the same hung workload.
- Why: Surya, MinerU, Docling, and PaddleOCR all treat OCR as a staged pipeline with explicit timing and failure boundaries. EYEX already had `concurrency.py` and `observability.py`, but they were not connected to the real OCR execution path, so a stuck engine looked like a generic failure and left no internal timing trail.
- Rejected: Blindly retrying timed-out OCR work, keeping timeout protection only in helper modules, and relying on outer HTTP timeouts as the only guardrail for local OCR hangs.
- Revisit when: OCR profiles need stage-specific timeout budgets or page-parallel scheduling that should move timeout policy from global settings into profile-owned route contracts.

## 2026-05-05 - OCR regression profiles are versioned config, not ad hoc notes

- Decision: EYEX now has first-class `config/ocr_evaluation_profiles/*.yaml` OCR regression profiles plus a repository command entrypoint (`scripts/run-ocr-eval.ps1`). OCR regression cases point to versioned fixture documents and page-level truth text, and the runner emits weighted CER/WER summaries with OCR engine and trace metadata.
- Why: Surya, MinerU, Docling, and PaddleOCR all depend on repeatable OCR benchmarks, not just qualitative review. EYEX already had CER/WER utilities, but no config-owned way to run them against stable fixture documents, so OCR optimization ideas could not be turned into a consistent regression gate.
- Rejected: Keeping OCR evaluation only in markdown notes, reusing extraction eval profiles for page-text OCR truth, and introducing sample-dependent runtime data under ignored directories as the first benchmark source.
- Revisit when: The project has a reviewed de-identified medical OCR corpus large enough to justify fielding separate benchmark tiers for layout, table structure, and end-to-end extraction.

## 2026-05-05 - OCR failures and latency must be diagnosable end-to-end

- Decision: Processing diagnostics now propagate OCR engine errors, OCR trace summaries, selected engine, slowest OCR stage, timeout counts, and stage timings from backend processing runs to the frontend diagnostics strip. The UI prefers explicit execution failure reasons such as timeout, DirectML runtime failure, and sidecar call failure over generic "engine not ready" text when a run actually attempted OCR work.
- Why: A long-running OCR failure that ends as "缺失 0 / 尝试 1" hides the real bottleneck and makes the operator debug the wrong layer. Mature OCR stacks expose execution-stage evidence, not only dependency readiness, especially when hybrid routes can be configured correctly but still fail at runtime.
- Rejected: Keeping dependency-readiness text as the only failure surface, relying on log inspection to distinguish timeout vs DirectML crash vs sidecar outage, and adding more runtime switches before the current chain is observable.
- Revisit when: The app has a richer diagnostics page that can render full OCR trace stages directly without squeezing the summary through `step_timings` and compact status text.

## 2026-05-06 - NVIDIA OCR uses the same canonical layout pipeline as Radeon

- Decision: The `cuda_paddle` OCR profile now routes scanned/image/table pages through `paddleocr_hybrid` with PP-StructureV3 as the required layout/table stage and PP-OCRv5 Paddle CUDA as the text-recognition stage, producing canonical `ocr-canonical-layout-v3` output.
- Why: NVIDIA CUDA acceleration should improve throughput without bypassing the final OCR business contract for precise boxes, visual reading order, table cells, candidate suppression, and structured traces. Running raw CUDA engines independently would reintroduce a second OCR path with different layout semantics.
- Rejected: Keeping separate direct engine routing for CUDA, falling back to Docling or PaddleOCR-VL CPU stages in the CUDA profile, and letting GPU vendor choice change the extraction-facing `DocumentIR` contract.
- Revisit when: A validated CUDA OCR engine emits canonical layout, text, table cells, and reading order with equal or better regression scores than the hybrid merger.

## 2026-05-06 - Source OCR and model schemas preserve table evidence

- Decision: Source OCR payload filtering must preserve numeric boxed OCR values such as ages, scores, dates, and table cells; only explicit Chinese page-marker text is suppressed. OpenAI Responses structured-output schemas are strict-mode compatible, including bounded conflict objects with `additionalProperties: false` and required nullable fields.
- Why: Numeric-only OCR boxes are business data in medical forms, not disposable page chrome. Strict provider schemas prevent upstream request rejection and keep model conflict output auditable without accepting arbitrary JSON.
- Rejected: Hiding all digit-only OCR candidates in the source view, relying on frontend overlays to recover numeric cells, and leaving open-ended schema objects in strict JSON-schema payloads.
- Revisit when: The canonical OCR layer stores page markers as a first-class block type that can be filtered without text heuristics, or provider schemas are generated from Pydantic models with automated strict-schema validation.

## 2026-05-06 - Table cells remain atomic through extraction and export

- Decision: Layout normalization must not merge table cells into same-line text blocks. Exact configured label cells may derive local `layout_key_value` blocks from adjacent same-row value cells, and those derived blocks are the evidence used by extraction/export. Runtime OCR readiness now treats profile mismatch or CPU-backed sidecars as not ready for GPU profiles.
- Why: Hospital homepage tables often encode business fields as separate cells (`性别 | 男`, `年龄 | 58`). Merging cells destroys table provenance, while failing to derive key-values causes missing structured export. GPU profile readiness must prove the configured accelerator path is active rather than silently accepting a stale or CPU sidecar.
- Rejected: Letting same-line OCR text merge table cells, relying on LLM prompts to infer table label/value relationships, accepting sidecar `/health` as ready without profile/device checks, and keeping untracked debug scripts as undocumented fallback workflows.
- Revisit when: OCR engines emit a trusted first-class table schema with label/value cell links and a supervised process manager can enforce sidecar profile/device alignment before backend startup.

## 2026-05-06 - Hardware OCR evals are blocked unless real corpus and GPU route exist

- Decision: The medical OCR regression profile declares a real-hardware contract (`requires_real_hardware`, `requires_deidentified_corpus`, minimum case count, and target accelerator list) and the eval runner exits non-zero when that contract has no fixtures, unless explicitly asked to print the blocker report. Any non-empty real-hardware case must now include page truth, block annotations with bbox/order/text, and table cell truth for layout/table evaluation.
- Why: Mock text fixtures prove the eval harness, not NVIDIA/AMD OCR precision, table layout quality, or image/PDF recognition. Completion reports must not imply hardware OCR readiness without a de-identified corpus and an active DirectML/CUDA/ROCm route.
- Rejected: Treating the mock OCR profile as evidence for production hardware readiness, silently passing an empty medical eval profile, and documenting GPU precision as complete from readiness probes alone.
- Revisit when: At least five de-identified medical image/PDF cases with page-level truth text and table/field expectations are available for DirectML, CUDA, and ROCm remote runs.

## 2026-05-06 - OCR eval reports include hardware readiness evidence

- Decision: OCR eval reports now include an `environment` payload with local accelerator probes, per-target readiness for `directml`, `cuda`, and `rocm_remote`, and copyable run/probe commands. `scripts/run-ocr-eval.ps1` prefers the project `.venv-ocr` runtime when present, and `real_hardware_case_template` is a blocked template profile with complete page/block/table annotation shape.
- Why: The target workstation can have usable DirectML assets while system Python, Paddle CUDA, ROCm, or remote VL are missing. The eval output must distinguish "harness works", "DirectML appears installed", and "real GPU OCR precision verified on a de-identified corpus".
- Rejected: Relying on external notes for environment evidence, defaulting evals to whichever `python` is first on PATH, and keeping the manifest template only inside markdown where tests cannot validate its contract.
- Revisit when: The hardware corpus is populated and the eval runner needs accelerator-sliced scoring for the same cases across DirectML, CUDA, and ROCm remote hosts.

## 2026-05-06 - OCR regression scores layout/table truth, not text alone

- Decision: OCR eval reports now score truth block annotations with text match, bbox IoU, center tolerance, and reading-order accuracy, and score truth table cells with cell text, row/column key preservation, and bbox/center accuracy. These metrics are reported per case under `layout_metrics` and `table_metrics`, with weighted summary averages when truth annotations exist.
- Why: CER/WER can pass while table cells are swapped, boxes drift off the source image, or reading order breaks downstream extraction. The real-hardware OCR contract already requires block and table truth, so the eval runner must use those annotations instead of storing them as inert metadata.
- Rejected: Waiting for a full PubTables-style structure metric before adding any layout signal, and treating exact table object reconstruction as required before useful cell-level regression scoring.
- Revisit when: A reviewed de-identified corpus exists and the project can add stricter table structure metrics such as row/column span graph accuracy and accelerator-sliced layout thresholds.

## 2026-05-06 - Stale OCR sidecars must fail with restart instructions

- Decision: The OCR sidecar `/health` payload now exposes `api_contract_version=eyex-ocr-sidecar-v2` and a build id. Backend runtime readiness and the HTTP OCR adapter reject local sidecars missing that contract, and the adapter turns known pre-fix NumPy parser failures into restart-required OCR errors instead of treating them as ordinary empty results.
- Why: A stale long-running sidecar can keep serving old code after repository fixes, causing eval/API failures that look like OCR quality problems. The operator needs a precise restart instruction, not a process kill or generic "no blocks" report.
- Rejected: Killing sidecar processes from eval/API code, silently accepting old health payloads, and relying only on log inspection to spot known stale-parser failure strings.
- Revisit when: EYEX has a supervised process manager that can restart sidecars safely and atomically during local upgrades.

## 2026-05-17 - Governance baseline tightened: complexity ceiling, dependency rules, perf baselines

- Decision: AGENTS.md now declares (a) a 500-line single-file ceiling for backend Python and frontend TS/TSX, with a "next task touching the file must split" rule, (b) a 60-dirty-file ceiling on long-running branches that blocks new feature work, (c) a 2-week life cap on `codex/<goal>` branches, (d) explicit architecture boundaries forbidding business pipelines from importing protocol adapters directly and forbidding `ocr_engine/` from owning profile-driven layout rules, (e) a Dependency Management section requiring exact pins, supply-chain checks, and typo-adjacency review, (f) a Testing Discipline section introducing pytest markers (`unit`/`contract`/`regression`/`slow`/`needs_gpu`) and an 800-line ceiling on test files, (g) Performance Baselines (single-page OCR P95 ≤ 12s on DirectML PP-OCRv5, single-field evidence-first extraction P95 ≤ 6s on DeepSeek v4-flash, > 30% regression must be flagged), (h) a quarterly dead-field prune for `ExtractionCandidate`/`EvidencePack`/`EvidenceCandidate`/`DocumentIRBlock`.
- Why: A repo audit found 5 source files over 600 lines (top: `EvidencePanel.tsx` 2017, `routes.py` 810, `layout_normalizer.py` 767, `ChartLensApp.tsx` 703, `model_providers.py` 659), 1 test file over 1000 lines, 97 in-progress dirty files on the active branch, and the dev-vs-main divergence on whether `application/` exists. Without explicit ceilings and triggers, these patterns recur in every refactor.
- Rejected: Soft "consider splitting" guidance without a numeric trigger; lint-only enforcement (does not catch the architecture boundary rules); a single big-bang refactor task in PLAN that mixes triage, layer decision, DB migration, and provider split.
- Revisit when: The ceilings stop reflecting real complexity (e.g., a single domain layer legitimately needs > 500 lines and splitting hurts cohesion), or when the project gains a second regular contributor and lint/CI rules can replace written norms.

## 2026-05-17 - Pending: application/ vs services/ flat layout

- Decision: PENDING. The dev branch (current) deletes the `backend/app/application/` package that exists on main (with `cases.py`, `document_fragments.py`, `evidence.py`, `llm_context.py`, `process_case.py`, `ports/`, `rule_extractor.py`, etc., totalling ~2000 lines) and merges its responsibilities back into `backend/app/services/`. The next focused task (`codex/architecture-decision`) must choose one of: (1) restore `application/` as the orchestration layer with `services/` reduced to protocol/framework adapters, or (2) keep the flat `services/` shape but enforce subpackage boundaries (`services/extraction/`, `services/ocr_engine/`, `services/llm_provider/`, `services/observability/`, `services/persistence/`) plus the AGENTS.md 500-line ceiling.
- Why: The reverse-direction refactor on dev is now blocking other planned splits (provider three-tier, OCR/layout boundary, dead-field prune) because they all target the same module surface. PLAN.md and AGENTS.md cannot be coherent until the layer choice is recorded.
- Rejected: Letting the dev branch implicit choice stand without a decision entry; mixing the layer choice into another task; keeping a hybrid where some orchestration sits in `application/` and some in `services/`.
- Revisit when: The pending task `codex/architecture-decision` lands; this entry is then replaced with a dated decision recording the chosen layout and a one-line completion summary.

## 2026-05-17 - dev is the default integration target; main is promoted in batches

- Decision: Every routine change commits to `dev` directly after passing local quality gates. `codex/<goal>` branches are reserved for tasks that genuinely need isolation (uncertain blast radius, parallel exploration, or large refactors with intermediate broken states), and they fast-forward back into `dev` after task-specific verification. `main` is promoted only when `dev` has accumulated enough finished change and is stable, with at least one full quality-gate pass and a recorded promotion note. Direct pushes to `main` remain forbidden.
- Why: This project is single-developer with Codex assistance. The previous "every change must go through a `codex/` branch" rule produced empty branch shells, frequent merge ceremony, and a backlog of branches that drifted from `dev`. Letting routine commits land on `dev` directly while still gating `main` keeps the audit trail and the promotion checkpoint without the branch-per-task overhead.
- Rejected: Merging every change into `main` directly (no integration buffer), maintaining one long-running `codex/<goal>` branch per subsystem (drift), squashing `dev` history before promoting to `main` (loses task-level rollback granularity).
- Revisit when: A second contributor joins, or a release/deployment cadence emerges that needs explicit release branches off `main`.

## 2026-05-18 - rule_pre_accepted shortcut bypasses LLM for high-confidence rule_shortcut groups

- Decision: `_extract_document_evidence_first` (`backend/app/services/pipeline.py`) now partitions phase-1 fields into two sets before invoking `evidence_provider.collect_evidence`. A field is rule-pre-accepted when its group's `semantic_strategy == "rule_shortcut"` AND `rule_shortcut_extract(field, document_ir.blocks)` returns a candidate with `confidence >= 0.95`. Pre-accepted candidates are tagged with `acceptance_reason="rule_pre_accepted"` and `provenance` extended with `{"source": "rule_shortcut", "skipped_llm": True, "decision_status": "PASS"}` (the `decision_status="PASS"` mirror is required because the export gate in `services/export.py` admits a result only when `validation_state == "accepted"` AND `provenance.decision_status == template.export_gate.pass_decision_status`; without it, gender / age extracted by the rule path would land in the workbook as `unknown`). All other phase-1 fields go to `llm_fields` and continue through `collect_evidence`, `adjudicate_fields`, `verify_against_document`, and `decisions_to_extraction_candidates` exactly as before. Trace `field_count` reflects the reduced LLM count. After `candidates_by_key` is built from the LLM stages, `rule_shortcut_candidates` is merged in (rule wins) so a stale or misbehaving LLM result cannot overwrite the bypass.
- Why: E1-010 Phase A (2026-05-18) surfaced that `eval-mock-003 / age` on the LLM baseline returned `normalized_code='integer'` — the LLM echoed the schema's `allowed_codes=[integer, unknown]` placeholder literal instead of the actual `'72'`. The rule path (`_extract_age`) returned `'72'` correctly at confidence 0.96. The honest fix per docs/REFERENCE_PROJECTS.md "PaddleOCR profile-driven shortcut pattern" is to skip the LLM whenever a deterministic high-confidence rule has already produced the answer. This both closes the precision regression and reduces token cost on every demographics-group call (gender / age / hospital when rule confidence ≥ 0.95 no longer round-trip through DeepSeek). The existing `services/rules.py` already returns `confidence >= 0.95` only for unambiguous strong patterns (`年龄 ?: ?\d{1,3} ?岁`, `患者，男/女，\d{1,3}岁`, gender label match), so the threshold is a self-documenting safety bar; weaker rules (`_extract_hospital` at 0.88) continue to defer to the LLM.
- Rejected: (1) Disabling the LLM for the entire `demographics_group` (would regress hospital and urban_residence on cases where the rule misses or returns sub-0.95 confidence); (2) implementing the shortcut inside `services/evidence_first.collect_local_evidence` (the rule path runs there for evidence ranking; tagging there would still let the LLM see the field and waste tokens; the bypass must happen in pipeline.py before `collect_evidence` is invoked); (3) deleting the schema's `allowed_codes=[integer, unknown]` placeholder for `age` (the schema treats `integer` as a type-class marker that the validator interprets via `_allowed_code` integer-digit check; it is consumed elsewhere); (4) adding a per-field `bypass_llm_when_rule_confident` flag (would scatter the policy across YAML and reduce schema readability when the existing `semantic_strategy: rule_shortcut` already declares the intent at the group level); (5) blanket-overwriting `acceptance_reason` to `rule_pre_accepted` after `validate_candidate` runs even on non-shortcut fields (would erase the existing `high_confidence_evidence_validated` / `requires_review` distinctions for LLM-extracted fields).
- Revisit when: a non-`rule_shortcut` group gains a high-confidence deterministic rule path (would justify reading `evidence_policy.high_risk` and the rule confidence directly rather than the group strategy); the `_extract_hospital` rule is widened to confidence ≥ 0.95 and consistently matches Chinese hospital-name conventions (would fold `hospital` into the bypass set); or a real-corpus baseline surfaces a case where the rule returns confidence ≥ 0.95 but produces the wrong answer (would force a tighter rule contract or a min-confidence-with-human-review tier between `rule_pre_accepted` and the existing LLM path).

## 2026-05-18 - Evidence-first prompt promotes field-level policy above generic rules

- Decision: Rewrite `_evidence_first_system_prompt` so the cacheable prefix explicitly tells the LLM to honor each field's `evidence_policy.implicit_negative_policy`, `evidence_policy.allowed_evidence_sources`, `evidence_policy.forbidden_inference_sources`, and `allowed_codes` BEFORE applying the generic "missing means unknown" rule. Medical section-complete implicit-negative patterns (`既往史：无特殊`, `未见异常`, `无明显异常`, with `个人史 / 系统回顾 / 病史` variants) are enumerated in the prompt as valid sources of `normalized_code='0'` candidates when (and only when) the field policy authorizes them. `EVIDENCE_FIRST_PROMPT_VERSION` is bumped to `eyex-evidence-first-v2` so cached results under the previous prompt are invalidated. Clause-bounded negation guidance is preserved (mirrors the 2026-05-17 `_positive_span` clause fix). The prompt remains byte-stable across cases so DeepSeek prompt-cache hits accumulate.
- Why: the 2026-05-18 LLM baseline (E1-011 Phase 2) recorded mock_general accuracy 0.9259 with all 4 failures on `eval-mock-007` where `既往史：无特殊` should map to chronic-disease=0. The schema field policies already declare `implicit_negative_policy: section_complete_only` and include `implicit_negative` in `allowed_evidence_sources`, but the previous prompt's generic safe-unknown rule overrode the policy. The rewrite resolves the contradiction by ordering: field-level policy first, generic rule only as fallback. The result is accuracy 0.9259 → 1.0 plus 47.8% input-token reduction, because a tighter prompt also ends model uncertainty earlier.
- Rejected: adding a per-field "this field accepts implicit negative" hint inside the dynamic user payload (would break cache stability and require a per-case prefix); switching to chain-of-thought prompting (per arxiv:2408.12249 CoT degrades biomedical IE); manually fine-tuning a DeepSeek prompt for medical clinical narratives (not in scope; would reintroduce drift between adapter prompts).
- Revisit when: a real-corpus baseline (E2-001 / E2-002) exposes a new failure pattern that the v2 prompt does not handle; or a new schema enables a field whose `evidence_policy` does not fit the current binary-with-implicit-negative shape; or the schema gains `allowed_codes` semantics that the prompt does not yet enumerate (currently '0' / '1' / 'unknown' with allowed_codes locking).

## 2026-05-18 - Seventh batched dev to main promotion (9dedc7c -> be04ad6)

- Decision: Promoted `dev` to `main` as a single fast-forward, taking `origin/main` from `9dedc7c` (Sixth promotion record) to `be04ad6` (E1-005 rule_pre_accepted shortcut). The 2-commit batch lands one fixture-coverage increment plus the E1-005 closure that surfaced from it: (1) `090750a` E1-010 Phase A added `eval-mock-009` (urban address + hospital label) and `eval-mock-010` (rural address + hospital label), extended `eval-mock-005` gold to anchor the unknown path, and pinned the address-redaction privacy boundary with a new parametrized test; rule-only baseline rose from 1.0 (54/54) to 1.0 (72/72) with LLM-assisted dropping to 0.9722 (70/72) on two unrelated honest LLM gaps. (2) `be04ad6` E1-005 closed the rule_pre_accepted shortcut: `_extract_document_evidence_first` now partitions phase-1 fields into rule-pre-accepted (group `semantic_strategy=rule_shortcut` AND `rule_shortcut_extract` confidence >= 0.95) versus LLM-bound, with `acceptance_reason="rule_pre_accepted"` and `provenance.{source=rule_shortcut, skipped_llm=True, decision_status=PASS}` tagging; the eval-mock-003 / age LLM gap is closed deterministically (LLM no longer sees `age` in fields) and the LLM-assisted baseline rises from 0.9722 to 0.9861 (71/72). New asserting-fake-provider regression test in `test_evidence_first_extraction.py` is the contract ratchet. Backend tests 342 -> 343. Plus this promotion record.
- Why: this batch carries two precision wins and a measured trade-off. Phase A widens the contract surface so the next 11-field expansion has a measured starting point (not a guess); E1-005 closes the canonical "the LLM should not have been called" gap that Phase A surfaced, and does so by reading the existing `semantic_strategy: rule_shortcut` group declaration — no new YAML, no new schema field, no new policy. Promoting now locks both wins onto main so future precision work compares against a 1.0/72 rule floor and a 0.9861/72 LLM floor on a 10-case fixture set. The single residual LLM failure (`eval-mock-009 / hospital` returning `'text'`) is documented as the next prompt-rewrite target and is not a regression — it was masked before Phase A added the hospital field to the contract.
- Verification at promotion time: backend pytest 343 passed in ~30 s (340 prior + 2 Phase A privacy tests + 1 E1-005 contract test); frontend npm test 9 passed; frontend npm run build OK (1839 modules, 122.71 kB gzip, ~590 ms); project-governance-check passed (only the pre-existing styles.css 3211-line warning, tracked as `PLAN-split-styles-css`). Both rule-only and LLM-assisted baselines reproduce: `python scripts\bootstrap-eval-fixtures.py --profile-id mock_general --baseline` and `Remove-Item var\storage\llm_cache -Recurse -Force; python scripts\bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --unsafe-eval-allow-remote-context --baseline`.
- Skipped intentionally: the v3 prompt rewrite that would close `eval-mock-009 / hospital` and `eval-mock-010 / diabetes_history` LLM paraphrase gaps. Both are documented as open follow-ups under E1-001 / E1-005 in `docs/ROADMAP.md` and will land as their own precision tasks with their own before/after evidence. PLAN-mock-general-phase-B (`tumor_history`) is also intentionally deferred because mixing fixture expansion with shortcut wiring would tangle two precision contracts in one commit.
- Residual risk: low-medium. The `pipeline.py` file is now 526 lines (over the AGENTS.md 500-line soft trigger; under the 800-line hard governance warning). The next task touching that file must include a split per the soft-trigger rule. The `eval-mock-009 / hospital` LLM placeholder-echo bug is structurally identical to the closed `eval-mock-003 / age` bug; widening the rule_pre_accepted shortcut to `_extract_hospital` is gated on raising the rule confidence threshold from 0.88 to >= 0.95 with stronger string-match patterns, which is its own precision task.
- Revisit when: pipeline.py is split (next file-touching task); a v3 prompt rewrite closes the residual LLM paraphrase gaps; or PLAN-mock-general-phase-B / C / etc. extends the fixture coverage further toward the 22-field schema.

## 2026-05-18 - Sixth batched dev to main promotion (f62336c -> 58b2854)

- Decision: Promoted `dev` to `main` as a single fast-forward, taking `origin/main` from `f62336c` (Fifth promotion record) to `58b2854` (E1-011 Phase 3). The 1-commit batch closes E1-011 entirely: `58b2854` lands real `collect_evidence` for `AnthropicMessagesProvider` (posts to `/v1/messages` with byte-stable system prompt + JSON schema descriptor in the cacheable `system` field) and `GoogleGeminiProvider` (posts to `/v1beta/models/<model>:generateContent` with `responseMimeType=application/json` + translated `responseSchema` via `_gemini_response_schema`); introduces `services/llm_provider/registry.py` as the single dispatch source replacing the if/elif chain in `fallback._provider_for_profile`; removes the dead adapter imports from `fallback.py`. New `test_provider_phase_3.py` (14 tests) pins payload byte-stability, real-implementation references, registry coverage of every catalog provider literal, `llm_mode` gating, and the `safe_evidence_only` privacy boundary fallback path. Backend tests 326 -> 340. Plus this promotion record.
- Why: this batch closes the architectural ratchet that started on 2026-05-18 with Phase 1. After the batch, every concrete `SemanticExtractionProvider` adapter has a real evidence-first implementation; no adapter inherits a silent fallback shim; every `provider` literal in `config/model_providers/mainstream.yaml` resolves through the registry; and the registry coverage test catches drift between catalog and code in CI. Promoting now makes the closed E1-011 contract visible on `main` so future precision tasks (E1-002 prompt-cache discipline, E1-003 retry-with-validation, E1-004 layout-aware windowing) start from a stable multi-provider baseline rather than a half-implemented one.
- Verification at promotion time: backend pytest 340 passed in ~30 s (326 prior + 14 new Phase 3 contract tests); frontend npm test 9 passed; frontend npm run build OK (1839 modules, 122.71 kB gzip, ~574 ms); project-governance-check passed (only the pre-existing styles.css 3211-line warning, tracked as `PLAN-split-styles-css`). Two consecutive backend test runs both green, confirming the cache-leak fix in `test_provider_phase_3.py` is durable.
- Skipped intentionally: the `Router.with_retries()` / `Router.with_fallbacks()` LiteLLM class extraction (recorded in `docs/DECISIONS.md` 2026-05-18 "Provider registry replaces if/elif dispatch": `ModelFallbackProvider` already separates fallback iteration from per-adapter retry/cooldown; a class split would be churn without behavior change). Removal of the legacy `extract_group` path is also intentionally deferred because the medical schema's `aneurysm_group`, `surgery_group`, `score_group`, `discharge_group`, and `history_group` all select `llm_semantic` or `llm_facts_then_compute` strategies that route through `extract_group`; deletion would require a coordinated schema rewrite that is out of scope for the architectural batch.
- Residual risk: low-medium. Anthropic and Gemini real calls are not yet exercised against an actual API key in this repository (no `mock_general_anthropic.json` / `mock_general_gemini.json` baseline exists). The `mock_general_llm` baseline (DeepSeek v4-flash via `OpenAICompatibleChatProvider`) is unchanged at 1.0/54 because Phase 3 did not touch that adapter's behavior. Risk is bounded by the 14 contract tests pinning payload shape, byte stability, real-implementation references, and the privacy boundary fallback path; any regression that hides the remote call behind a shim, breaks the cacheable prefix, or lets `safe_evidence_only` leak to the network will fail the suite immediately.
- Revisit when: Phase 3 baselines for Anthropic and/or Gemini land (requires real API keys); E1-002 (DeepSeek prompt-cache prefix discipline) measures `cache_hit_rate` against the byte-stable v2 prompt and confirms the Phase 3 cacheable-prefix discipline carries over to Anthropic and Gemini's native context-caching mechanisms; or a new provider literal is added to the catalog YAML and the registry coverage test catches it.

## 2026-05-18 - Provider registry replaces if/elif dispatch

- Decision: `services/llm_provider/registry.py` is the single source for mapping a `ModelProfile.provider` literal to the concrete `SemanticExtractionProvider` adapter class. The old `fallback._provider_for_profile` if/elif chain is now a thin delegating shim that calls `registry.provider_for_profile`. Each registry entry pairs an adapter factory with the set of `settings.llm_mode` values it accepts (`{auto, online}` for cloud-only adapters, `{auto, online, local}` for `openai_compatible` because it can talk to local Ollama/LM Studio servers via base_url override). Adding a new provider literal means one registry entry, not three places (catalog YAML, adapter class, dispatcher branch). Contract test `test_registry_covers_every_catalog_provider` enforces that the catalog and the registry stay in sync; `test_registry_dispatches_each_known_kind` enforces that every literal constructs the right adapter class; `test_registry_rejects_unknown_provider_kind` and `test_registry_rejects_remote_kind_in_local_mode` enforce the failure paths. The `disabled` provider is a sentinel that returns `ConservativeLocalProvider` regardless of `llm_mode`, preserving the existing off-switch.
- Why: the if/elif chain encoded the same provider literals four times (the chain itself, the catalog YAML, the adapter class registration, the contract test). A new provider was easy to add to three of those places and forget the fourth, and the chain order silently determined dispatch precedence. The data-driven table compiles to one declarative source. Phase 3 of E1-011 was the natural moment to extract it because four adapters now have real implementations and the if/elif had grown to 8 lines that had to change in lockstep.
- Rejected: introducing a `Router` class with `with_retries()` and `with_fallbacks()` methods (the LiteLLM pattern) at the same time. `ModelFallbackProvider` already separates fallback iteration (its `extract_group`/`collect_evidence` outer loop) from per-adapter retry (the API-key cooldown loop inside each adapter), so the structural goal is met without a rename; introducing a `Router` class would be churn without behavior change. Also rejected: removing the legacy `extract_group` path. Every adapter still implements it and removing it requires a coordinated schema update; deferred to a future task.
- Revisit when: the LiteLLM Router pattern becomes load-bearing because EYEX adopts a multi-tenant routing requirement (round-robin per-key, weight-based fallback, model-tier degradation), or when we add a fifth adapter and the registry shape no longer fits (for example, when a vendor needs to declare both a streaming and a non-streaming variant under one logical provider).

## 2026-05-18 - Fifth batched dev to main promotion (b2d9fd3 -> 6344ce1)

- Decision: Promoted `dev` to `main` as a single fast-forward, taking `origin/main` from `b2d9fd3` (Fourth promotion record) to `6344ce1` (E1-001 evidence-first prompt rewrite). The 1-commit batch is the focused E1-001 precision win: `6344ce1` rewrites `_evidence_first_system_prompt` so field-level `evidence_policy` (especially `implicit_negative_policy: section_complete_only` and `allowed_codes`) sits above the previous generic safe-unknown rule. Medical implicit-negative patterns (`既往史：无特殊`, `未见异常`, `无明显异常`, plus `个人史/系统回顾/病史` variants) are now explicit in the cacheable prefix; `EVIDENCE_FIRST_PROMPT_VERSION` bumped to `eyex-evidence-first-v2` so old cache entries auto-invalidate. Cache stability and clause-boundary rules preserved. New `backend/tests/test_evidence_first_prompt.py` (8 tests) pins prompt structure, byte-stability, no per-case data leak, and policy-vs-generic ordering. Plus this promotion record.
- Why: this batch is intentionally narrow because the precision win it carries is meaningful in isolation. The `mock_general` LLM baseline rose from 0.9259 to **1.0** (50/54 → 54/54), input tokens dropped from 72,372 to 37,792 (-47.8%), output tokens dropped from 18,757 to 11,170 (-40.4%). All 4 known `eval-mock-007` chronic-disease failures are closed by a single root cause fix in the prompt itself, with no schema or adapter change required. Both the rule-only and LLM-assisted baselines now sit at 1.0/54; further precision gains require a real-world corpus (E2-001 / E2-002) where new gaps emerge naturally. Promoting a single-commit batch keeps the precision ratchet visible on `main` and gives any future precision regression a clean reference point: the v2 prompt at this exact line count and structure is the floor.
- Verification at promotion time: backend pytest 326 passed in ~26 s (318 prior + 8 new prompt-pinning tests); frontend npm test 9 passed; frontend npm run build OK (1839 modules, 122.71 kB gzip, ~524 ms); project-governance-check passed (only the pre-existing styles.css 3211-line warning, tracked as `PLAN-split-styles-css`). LLM baseline reproducible via `Remove-Item var\storage\llm_cache -Recurse -Force; python scripts\bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --unsafe-eval-allow-remote-context --baseline`.
- Skipped intentionally: E1-011 Phase 3 (Anthropic + Gemini + router/registry split) and PLAN-mock-general-phase-A (demographics field expansion). Both are independent PLAN tasks and would have widened this batch beyond the single E1-001 theme. The 47.8% input-token reduction is a side effect of the prompt rewrite and is recorded as evidence; it is not a separate optimization.
- Residual risk: low. The change is prompt content only; no adapter, schema, or pipeline code path moved. The cacheable prefix remains byte-stable across calls (verified by `test_prompt_is_byte_stable_across_calls`) so DeepSeek prompt-cache discipline is preserved for E1-002. The version bump to `eyex-evidence-first-v2` automatically invalidates any stale cache entries from the v1 prompt without manual cleanup. The 8 new pinning tests catch any future drift in policy-vs-generic ordering, byte stability, or implicit-negative pattern coverage.
- Revisit when: E1-002 (DeepSeek prompt-cache prefix discipline) measures `cache_hit_rate` against the v2 prompt and either confirms the prefix is stable or surfaces a per-case leak that needs a v3 prompt; or a real-corpus baseline (E2-001 / E2-002) exposes a new failure pattern that the v2 prompt does not handle; or a new schema enables a field whose `evidence_policy` does not fit the binary-with-implicit-negative shape.

## 2026-05-18 - Fourth batched dev to main promotion (aed2d8e -> b0f776d)

- Decision: Promoted `dev` to `main` as a single fast-forward, taking `origin/main` from `aed2d8e` (Third promotion record) to `b0f776d` (E1-011 Phase 2). The 8-commit batch covers the second wave of fixture-driven precision work plus the architectural refactor that finally connects DeepSeek to the evidence-first extraction path: (1) `5ce9abf` extends `mock_general` from 5 to 7 fixtures; (2) `aecb7b9` adds `eval-mock-008` challenge case exposing synonym recall gaps; (3) `2930738` adds field-coverage and OCR post-processing research docs; (4) `eb31204` closes E1-005 synonym widening and adds the LLM connectivity check; (5) `124d9bf` bootstraps the LLM baseline and surfaces the OpenAI-compatible adapter gap; (6) `71a4884` writes the deep-dive `docs/LLM_PROVIDER_REFACTOR.md`; (7) `fd9527d` lands E1-011 Phase 1 (`collect_evidence` becomes `@abstractmethod`, contract test pins the rule); (8) `b0f776d` lands E1-011 Phase 2 (real DeepSeek call through `OpenAICompatibleChatProvider.collect_evidence`, `mock_general_llm` baseline at 0.9259 with non-zero tokens); plus this promotion record.
- Why: this batch closes the architectural gap that blocked every prior LLM precision claim from being measurable. Before the batch, the `mock_general_llm` baseline was a fake (zero tokens, silent fallback to rule extraction). After the batch, the LLM path produces real `input_tokens=72,372`, `output_tokens=18,757` numbers, the failure pattern (`既往史：无特殊` interpreted as unknown rather than 0) is a single root cause, and E1-001 prompt rewrite has a real before/after reference. Promoting now makes the working precision ratchet visible on `main` so any clone of the project sees the LLM path in working condition.
- Verification at promotion time: backend pytest 318 passed in ~26 s (303 prior + 15 new contract tests for E1-011 Phase 1); frontend npm test 9 passed; frontend npm run build OK (1839 modules, 122.71 kB gzip, ~553 ms); project-governance-check passed (only the pre-existing styles.css 3211-line warning); LLM baseline reproducible via `Remove-Item var\storage\llm_cache -Recurse -Force; python scripts\bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --unsafe-eval-allow-remote-context --baseline`.
- Skipped intentionally: E1-011 Phase 3 (Anthropic + Gemini + router/registry split). It is one independent PLAN task and would have widened this batch beyond a single coherent theme. The 4 known LLM failures on `eval-mock-007` are also intentionally not closed; that is the E1-001 prompt-rewrite target and must come with its own before/after measurement commit.
- Residual risk: medium-low. The biggest behavioral change is `OpenAICompatibleChatProvider.collect_evidence` running real network calls when triggered from `bootstrap-eval-fixtures.py --provider llm --unsafe-eval-allow-remote-context`. Production paths (FastAPI endpoints, the case-processing worker pool) are unaffected because the medical schema's `safe_evidence_only` policy still blocks remote upload of raw OCR text by default; the new process-local exposure-policy override is set only by the bootstrap script. The eval-mock-007 LLM regression is an honest baseline failure, not a code bug. The E1-011 Phase 1 contract test (15 new tests) catches any future adapter that re-introduces the silent-fallback shim.
- Revisit when: Phase 3 lands and a fresh promotion is needed; or E1-001 prompt rewrite produces the next baseline shift; or a real-corpus baseline (E2-001 / E2-002) replaces `mock_general` as the dominant precision contract.

## 2026-05-18 - Process-local exposure-policy override for eval-only LLM baselines

- Decision: Add `set_runtime_exposure_policy_override(policy)` in `services/llm_provider/payloads.py`. The bootstrap script `scripts/bootstrap-eval-fixtures.py` may opt into a full-context `RemoteExposurePolicy` via the `--unsafe-eval-allow-remote-context` flag; the override is process-local and never written to disk. Production code paths (FastAPI request handlers, the case-processing worker pool, any path triggered by an HTTP request) must NOT call `set_runtime_exposure_policy_override`. The schema-derived policy in `config/extraction_schemas/<id>.yaml` remains the only authoritative source for runtime behavior outside evaluation tooling.
- Why: the 2026-05-01 "Remote medical extraction is safe-evidence-only by default" decision blocks the medical schema from sending raw OCR text to a remote provider, which is correct for production. But it also blocks the LLM evaluation baseline (`scripts/bootstrap-eval-fixtures.py --provider llm`) from ever generating non-zero tokens on the synthetic `mock_general` fixtures, because the same medical schema is shared by the synthetic fixtures. Forking a parallel `mock_general_llm` schema would duplicate every field definition (22 fields) and create a maintenance hazard. The process-local override sidesteps that fork while preserving the production constraint: schema YAML is unchanged, the override does not persist, and only the bootstrap entrypoint is wired to set it.
- Rejected: forking `mock_general_llm.yaml` as a parallel extraction schema (duplicates 22 fields, new YAML drift surface); flipping the medical schema's `allow_full_document_context` to true (sends real PHI to remote providers in production); changing the runtime check to permit `safe_evidence_only` mode through the LLM (model has no raw text to ground evidence against, would return mostly empty results); using monkeypatch from a test or script (less discoverable; an explicit setter exposes the override in code review).
- Revisit when: a managed deployment profile with consent + DPA + retention controls allows production full-context remote calls; or a real-corpus baseline (E2-001 / E2-002) replaces the synthetic mock_general LLM baseline and the override is no longer needed.

## 2026-05-18 - Default-inheritance shim for collect_evidence is forbidden

- Decision: `SemanticExtractionProvider.collect_evidence` is `@abstractmethod`. Every concrete adapter must override it explicitly. An adapter that intentionally delegates to local rule extraction does so by calling `local_collect_evidence_fallback(document_context, fields)` and assigning `local_evidence_fallback_usage()` to `self.last_usage`. The base-class default body that previously hid this delegation is removed; `backend/tests/test_provider_contracts.py` enforces the rule and a `mainstream.yaml` provider entry without a corresponding adapter wiring fails the same suite.
- Why: the previous default body let `OpenAICompatibleChatProvider`, `AnthropicMessagesProvider`, and `GoogleGeminiProvider` silently fall back to rule extraction whenever the medical pipeline asked for evidence. The runtime ledger recorded zero input tokens, but the diagnostic looked identical to a legitimate "no LLM call needed" path. The 2026-05-18 baseline run (`config/evaluation_profiles/baselines/mock_general_llm.json`) surfaced the gap by recording `input_tokens=0` against a real DeepSeek profile. Making `collect_evidence` abstract turns the gap from a silent inheritance into a code review item: every adapter author must now decide between calling the upstream API and explicitly delegating, and the choice is visible in the source.
- Rejected: keeping the default shim and adding a runtime warning when adapters did not override it (warnings are easy to ignore; an abstract method is enforced by Python at class instantiation); spreading `collect_evidence` across the four adapters as a single commit before establishing the rule (the next adapter would re-introduce the same footgun); adding `evidence_collection_method=local_fallback` to `last_usage` only as the contract (a string literal is opt-in; abstractness is structural).
- Revisit when: the LLM provider layer adds a base class that intentionally provides a working default (for example a router base class that forwards to a default member adapter); or when the adapter set shrinks enough that only one or two concrete classes remain and the abstract method becomes ceremony.

## 2026-05-18 - LLM provider refactor planned in three phases

- Decision: Adopt the three-phase refactor described in `docs/LLM_PROVIDER_REFACTOR.md` to fix the architectural gap surfaced by the 2026-05-18 LLM baseline run (DeepSeek / Anthropic / Gemini / OpenRouter etc. silently fall back to rule extraction because only `OpenAIResponsesProvider` overrides `SemanticExtractionProvider.collect_evidence`). Phase 1 turns the gap into a hard error by making `collect_evidence` abstract; Phase 2 implements `OpenAICompatibleChatProvider.collect_evidence` so DeepSeek and friends actually call `/chat/completions`; Phase 3 covers Anthropic + Gemini and extracts a `Router` class plus a registry, modeled after LiteLLM's three-layer fallback / retry / completion architecture and LangChain's `BaseChatModel.with_structured_output`. Each phase is one PLAN task and ships independently. The refactor is the prerequisite for E1-001 (prompt rewrite), E1-002 (DeepSeek prefix cache), and E1-003 (retry-with-validation-feedback); none of those can produce meaningful before/after numbers until Phase 2 lands.
- Why: the gap is hidden by the default-inheritance shim in `SemanticExtractionProvider`. Closing it through ad-hoc adapter additions would re-introduce the same footgun for the next provider; making `collect_evidence` abstract is the structural fix. Phasing ensures that a Phase 2 bug never breaks the rule-only baseline floor (Phase 1 keeps explicit local fallbacks as the default behavior for every LLM adapter).
- Rejected: implementing all three adapters in one commit (too large, blast radius too wide); adding `collect_evidence` to one adapter at a time without first making the contract abstract (re-creates the same silent footgun for every future provider); deleting the evidence-first multimodal path and reverting to `extract_group`-only (would lose the layout-aware evidence collection that medical extraction depends on).
- Revisit when: the three phases land or a higher-priority precision task forces a different routing decision (for example a local-LLM fallback that requires a separate router).

## 2026-05-18 - User-authorized exception to the chat-pasted key rule

- Decision: Under explicit one-time authorization from the resource owner ("暂时授予你权限"), the user-supplied DeepSeek key was written to the local gitignored `.env` and a connectivity-check script was added under `scripts/check-llm-connectivity.py` (.ps1 wrapper). The script never prints the key value; it reports presence, length, fingerprint (first 2 + last 2 chars), and HTTP outcome, and writes a `model_calls` row tagged `stage=connectivity_check` to the durable observability ledger. Existing DPAPI-stored provider key was backed up to `var/storage/provider_secrets.json.bak-2026-05-18` and removed from the active store so the `.env` key is the active credential. The general rule from the same-day earlier decision still stands: future Codex sessions do not write chat-pasted keys to disk without an equivalent explicit authorization.
- Why: the resource owner accepted the documented risk that the key is already exposed in chat history and chose to proceed with end-to-end LLM evaluation work that requires a live key. Refusing again would block the user from operating their own system. Documenting the exception with bounded scope (one key, one authorization, one session) keeps the constitutional default intact for the next session.
- Rejected: silently using the key without writing it to disk (worse traceability), declining outright (overrides the resource owner's explicit informed authorization), permanently relaxing the rule (would normalize chat-channel key transport).
- Revisit when: the next chat-pasted key arrives without the same explicit "暂时授予权限" framing; or the project gains a managed secret broker so the user can hand keys to the broker without crossing the assistant transport channel.

## 2026-05-18 - LLM provider keys never enter chat or commits, even on user request

- Decision: LLM provider API keys (DeepSeek, OpenAI, etc.) are configured by the user through the EYEX provider settings UI (writes to OS-protected DPAPI store on Windows) or by editing the local gitignored `.env` directly. Codex sessions never write a user-supplied key to a file, never echo it back, never invoke a remote API on its behalf. If a user pastes a key in chat, the key is treated as already leaked from the moment of paste — it must be rotated, and the new key must reach the runtime through one of the two supported channels above. Codex confirms readiness through a `/v1/models` connectivity check that does not print the key value.
- Why: keys pasted into chat enter conversation history and any logging or storage downstream of the assistant transport. They cannot be unsent. Writing such a key to `.env` propagates the leak to disk; using it for any API call generates billing records under a compromised credential. The OS-protected provider settings path and the gitignored `.env` path were specifically designed in `AGENTS.md` to keep keys out of the assistant's transport channel; bypassing them on user request would normalize that bypass.
- Rejected: writing a chat-pasted key to `.env`; calling DeepSeek with the leaked key on user request; remembering the key for the rest of the session; treating "key already leaked anyway" as a reason to use it.
- Revisit when: the project gains a managed secret broker (Vault, KMS, cloud Secret Manager) where user-supplied keys can be handed to the broker without crossing the assistant transport channel. Until then, the two channels above remain the only valid paths.

## 2026-05-17 - Third batched dev to main promotion (746df16 -> fdaed1c)

- Decision: Promoted `dev` to `main` as a single fast-forward, taking `origin/main` from `746df16` (Second promotion record) to `fdaed1c` (clause-boundary positive span fix). The 2-commit batch is the precision-loop closure: (1) `9a8a483` locks the deterministic `mock_general` extraction baseline at `accuracy=0.90625` (29/32) with 5 synthetic Chinese inpatient fixtures, the bootstrap CLI, the baseline JSON, and the contract test that hard-codes the floor; (2) `fdaed1c` is the first end-to-end exercise of the AGENTS.md Precision Tasks contract — fixes the `_positive_span` clause-boundary leak in `services/evidence_first.py`, raises the baseline to `accuracy=1.0` (32/32), regenerates the baseline JSON, lifts the test floor, and pins two clause-boundary regression tests; plus this promotion record.
- Why: This pair finishes the precision contract loop. Before the batch, "AGENTS.md says precision tasks land with eval evidence" was a written rule with no demonstrated workflow; after the batch it is a working ratchet on disk that runs in CI: a behavior change that lowers the metrics fails immediately, a behavior change that raises them must regenerate the baseline JSON and lift the floor in the same commit. Promoting now makes the ratchet visible on `main` so any third-party clone of the project sees the new contract from the start instead of only on `dev`.
- Verification at promotion time: backend pytest 300 passed in ~24 s (includes 4 eval-fixture contract tests plus 2 new clause-boundary regressions); frontend npm test 9 passed; frontend npm run build OK (1839 modules, 122.71 kB gzip, ~488-524 ms across runs); project-governance-check passed (only the pre-existing `styles.css` 3211-line warning, tracked as `PLAN-split-styles-css`). The committed baseline `config/evaluation_profiles/baselines/mock_general.json` reproduces deterministically through `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline`.
- Skipped intentionally: the `rule_pre_accepted` shortcut half of E1-005 (skip LLM on high-confidence rule hits, surface the reason in diagnostics). It is explicitly scoped out in `docs/ROADMAP.md` and tracked as the next E1-005 sub-task. Splitting it kept this batch focused on the recall-gap fix that the baseline contract was actually built for.
- Residual risk: low. The behavior change is one helper function (`_positive_span`) with bounded blast radius (only the synonym-driven binary-history evidence path), full regression coverage in `test_evidence_first_extraction.py`, and a pinned baseline floor in `test_eval_fixtures.py`. The mock_general accuracy=1.0 floor is now the strictest precision contract on the project; any future change to evidence collection or layout normalization that perturbs these specific scenarios will fail loudly in CI.
- Revisit when: a future promotion fails fast-forward; the next E1 task lands and the precision baseline shifts (regenerate baseline + lift the test floor in the same commit per the established loop); or a real de-identified medical OCR corpus is wired in and `medical_inpatient_zh` evaluation profile becomes the dominant baseline (E2-001 / E2-002 territory).

## 2026-05-17 - mock_general accuracy raised to 1.0 via clause-boundary positive span fix

- Decision: Raise the `mock_general` rule-only baseline floor from `accuracy=0.90625` (29/32) to `accuracy=1.0` (32/32) by clipping `_positive_span` evidence windows at sentence terminators `。 ； ; \n` and only consulting LEFT-side negation. Right-side negation is part of a different field's clause and was incorrectly poisoning positive matches such as `高血压病史10年。否认糖尿病史。` and `吸烟史20年，每日10支。否认饮酒史。`. The new baseline JSON is committed in the same change, the contract test floor is raised from 0.90625 to 1.0 in the same commit, and two clause-boundary regression tests are added so this leak cannot reappear silently.
- Why: This is the first end-to-end exercise of the AGENTS.md Precision Tasks contract. The baseline test fired exactly as intended (`32 != 29`), forced the floor and the JSON to be regenerated together with the code change, and the change is therefore traceable: behavior change + eval evidence + regression pin in one commit.
- Rejected: Adding bespoke regex per-field rather than fixing the shared span helper (would have needed three new fragile patterns and left the underlying clause-boundary bug for the next field); raising the floor without the regression tests (would let the next refactor undo the gain silently); fixing only `_positive_span` and leaving the right-side window unbounded for `_negative_span` (the negative span helper already explicitly stops at `。；;\n` via its anchor regex, so no symmetric change was needed).
- Revisit when: a precision task lifts the floor again (bump the assertion in `test_baseline_file_is_present_and_well_formed` and regenerate the baseline JSON); or the synthetic fixture style stops representing real cases adequately and the baseline must be recomputed against a real de-identified corpus.

## 2026-05-17 - mock_general extraction baseline locked

- Decision: Lock the rule-only `mock_general` extraction baseline at `accuracy=0.90625` (29 of 32 fields), `auto_accept_precision=1.0`, `evidence_coverage=1.0`, `unknown_misfill_rate=0.0` against 5 synthetic Chinese inpatient fixtures committed under `config/evaluation_profiles/fixtures/mock_general/`. The on-disk baseline JSON `config/evaluation_profiles/baselines/mock_general.json` is the canonical "before" reference for any E1 precision task. The contract test `backend/tests/test_eval_fixtures.py::test_baseline_file_is_present_and_well_formed` hard-codes the accuracy floor at this value. Lifting the floor requires regenerating the baseline as part of a precision task and updating the test in the same commit.
- Why: Without an immutable, deterministic baseline the AGENTS.md Precision Tasks rule (every behavior change lands with eval evidence) is impossible to enforce. The rule-only baseline keeps the floor independent of remote LLM availability so CI can verify precision regressions even on a workstation with no API keys configured. The 3 known recall gaps (positive `hypertension_history` and `smoking_history` from "高血压病史10年" / "吸烟史20年" patterns) are intentionally left open so E1-001 (system prompt rewrite) and E1-005 (rule pre-filter widening) have a measurable target.
- Rejected: Backfilling positive history rules in the same commit (would conflate baseline establishment with rule improvement); using fully-correct fixtures only (would mask the recall gap and remove the precision target); placing the baseline JSON outside the repo (would break CI reproducibility); shipping LLM-assisted baselines as the floor (would couple the baseline to provider availability and key state).
- Revisit when: a precision task lifts the floor (regenerate baseline and update the floor in the test); the synthetic fixture style stops representing real cases adequately and a real de-identified fixture set replaces it; or a new schema field is added to demographics / history / lifestyle groups that should also enter the gold set.

## 2026-05-17 - Second batched dev to main promotion (4eb713a -> dc5e679)

- Decision: Promoted `dev` to `main` as a single fast-forward, taking `origin/main` from `4eb713a` (Make dev the default integration target) to `dc5e679` (feat: add field extraction eval runner). The 4-commit batch is a clean transition from "no governance, undocumented architecture" to "rules align with code, three authoritative docs, first roadmap task implemented": (1) `16e9eb4` AGENTS.md rewrite plus governance foundation; (2) `95444b1` ARCHITECTURE/ROADMAP/REFERENCE_PROJECTS docs; (3) `dc5e679` E0-008 field extraction eval runner with the canonical scoring service, CLI, and 9 new contract tests; plus this promotion record itself.
- Why: The dev branch reached a stable, internally consistent state. The Commit Traceability rule (every commit carries Refs and Verification footers), the Precision Tasks rule (every behavior change lands with eval evidence), and the Documentation Map (no `(planned)` tags left) are all observable in the dev tip. Holding the batch longer would not add stability; landing E0-008 first establishes the measurement contract that every subsequent E1 task depends on, so promoting now lets future precision work reference a stable main as the comparison baseline.
- Verification at promotion time: backend pytest 294 passed in ~27 s (includes 9 new extraction-eval tests); frontend npm test 9 passed; frontend npm run build OK (1839 modules, 122.71 kB gzip, ~717 ms); project-governance-check passed (only pre-existing styles.css 3211-line warning, tracked as PLAN-split-styles-css). routes.py is no longer in the large-file warning set after dropping to 653 lines.
- Skipped intentionally: nothing. All four dev commits were verified individually before landing, and all four ran against the same gates.
- Residual risk: low. The only behavior surface that changed is the FastAPI `/api/evals/*` routes, which now delegate to `services/extraction_eval.py`; the response shape extends rather than replaces (adds `status`, `schema_version`, optional `hard_blocker`, `blocker_message`). Frontend callers do not consume those endpoints today, and `BatchEvaluationResponse` plus `EvaluationProfileRunResponse` accept the additional keys via their existing `dict[str, Any]` fields. The `mock_general` and `medical_inpatient_zh` evaluation profiles still have empty gold case lists; the runner correctly reports this as `hard_blocker="no_gold_cases"`. Filling those gold cases is the next prerequisite for any E1 precision task that needs before/after numbers.
- Revisit when: A future promotion fails fast-forward (would indicate someone pushed to main directly), a third-party CI starts anchoring on main, or the next E1 precision task lands and requires re-baselining.

- Decision: Promoted `dev` to `main` as a single fast-forward, taking `origin/main` from `165362c` (Rename project to ChartLens) to `4eb713a` (Make dev the default integration target). The 8-commit batch covers: foundational dev upgrade, governance baseline tightening, EvidencePanel split, hand-written validators replaced with zod, IDE workspace ignored, in-progress ChartLens OCR/extraction upgrade integration, perf_counter timing fix, and the promotion-flow rewrite itself.
- Why: This is the first execution of the new "dev is default integration target; main is promoted in batches" rule. The 8 commits were each verified against full quality gates as they landed, and one final pre-promotion run (backend 285 passed, frontend 9 passed, npm run build OK, governance scan OK) confirmed dev was stable. Holding the batch any longer would have widened the gap between dev and main without adding stability.
- Verification at promotion time: backend pytest 285 passed (~62 s); frontend npm test 9 passed; frontend npm run build OK (1839 modules, 122.71 kB gzip); project-governance-check passed (only pre-existing routes.py 810 / styles.css 3211 large-file warnings).
- Skipped intentionally: test_ocr_engine_modules::test_trace_stage_timing was Windows-flaky on time.monotonic resolution and was fixed in 81e8889 (perf_counter); no other test was waived.
- Residual risk: 298 files / +37 104 / -11 010 is a large state jump for `main` viewed from any tooling that anchors on it. No third-party CI / deployment is anchored on `main` today, so blast radius is limited to local clones; the next clone of `main` will see the upgraded ChartLens shape directly.
- Revisit when: Either a release/deployment cadence emerges that needs explicit release branches, or a second contributor joins, or a future promotion fails fast-forward (which would mean someone bypassed the rule and pushed to `main` directly).


## 2026-05-18 - Documentation maintenance contract

- Decision: AGENTS.md gains a "Documentation Maintenance" section that codifies four rules: (1) one outcome narrative per task lives in exactly one file (DECISIONS.md when the change records a decision, otherwise PLAN.md Done); ROADMAP.md and PLAN.md Done are summaries plus an anchor link; (2) commit hashes do not appear in markdown — work is referenced by ISO date plus task ID; (3) every DECISIONS.md entry carries a `Status: active | superseded by <YYYY-MM-DD title> | archived (<reason>, <date>)` line and the supersedence pointer is bidirectional in the same commit; (4) the markdown 800-line soft ceiling triggers a split or archive rotation, and a quarterly stale-content sweep covers HEAD references, missing DECISIONS anchors, pending decisions, license re-verification, and `PLAN.md` Done rotation into `docs/PLAN_HISTORY.md`. Same commit also adds an "Active Index" header to DECISIONS.md so active entries are findable without scrolling, marks the two same-day-superseded PaddleOCR-VL entries (2026-05-01 "Radeon OCR defaults are GPU-guarded" and "PaddleOCR-VL AMD GPU means official ROCm sidecar") with explicit Status lines pointing at the surviving 2026-05-01 "PaddleOCR-VL is parked outside the default OCR route", marks the 2026-04-30 "GitHub branches are the personal Codex control boundary" superseded by 2026-05-17 "dev is the default integration target", and rotates 14 older `PLAN.md` Done entries to the new `docs/PLAN_HISTORY.md`.
- Why: the constitution had drifted into three failure modes that this rule set targets directly. (1) The same outcome narrative was being maintained in three files (PLAN.md Done, ROADMAP.md Outcome, DECISIONS.md), so two of the three drifted out of date on every promotion; defining one single source plus pointers fixes the maintenance cost. (2) Several docs embedded commit hashes (`Status as of 2026-05-18 (HEAD 124d9bf)` in `docs/LLM_PROVIDER_REFACTOR.md`, `dev HEAD 9dedc7c` in `docs/FIELD_COVERAGE.md`); those hashes were already stale at the time this rule landed because `dev` had advanced. Replacing hashes with date + task-ID stops the bit rot at the source. (3) Two same-day decisions about PaddleOCR-VL contradicted each other and the third one explicitly superseded both — but neither superseded entry carried any visible "this is no longer in force" marker, so a new session reading top-down would happily implement the wrong thing. The Status line + Active Index makes superseded content visible.
- Rejected: deleting superseded entries outright (loses the supersedence audit trail and the "why we changed our mind" rationale); auto-generating the Active Index from headings (the index needs hand-curated grouping by topic and explicit notes on what supersedes what; an alphabetical or chronological dump would not catch supersedence pairs); rotating all done entries to PLAN_HISTORY.md immediately (loses the recent-context "this is what just landed" benefit; keeping the latest 5 in PLAN.md preserves session-level continuity); waiting until the next quarterly sweep to apply this set of changes (the 14 already-rotatable Done entries plus the embedded HEAD hashes were causing concrete confusion in this session).
- Status: active.
- Revisit when: the documentation surface grows enough that a second writer needs the rules expressed differently (e.g., per-doc CODEOWNERS, automatic stale-link CI); or when a precision task in `dev` produces an outcome that does not fit the "one source per task" model (e.g., a multi-week experiment that legitimately needs a separate `docs/experiments/<id>.md` file); or when DECISIONS.md crosses the 800-line ceiling and the OCR sub-section needs to be archived to `docs/archive/ocr_decisions_2026q2.md`.
