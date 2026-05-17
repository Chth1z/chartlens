# Reference Projects

This is the registry of open-source projects EYEX studies for design ideas. The Reference Projects Policy in `AGENTS.md` governs how borrowing happens. The default mode is reference-only: cite the upstream design or algorithm with a commit-pinned URL, do not commit upstream source. Source-level reuse requires a clearly named adapter directory, full attribution, and a license decision in `docs/DECISIONS.md` for anything beyond plain MIT / Apache-2.0 / BSD.

License notes below were verified against the listed upstream URLs at the indicated check dates. Re-verify before any source-level reuse.

## OCR and Document Parsing

### PaddleOCR (PP-OCRv5, PP-StructureV3)

- Upstream: [github.com/PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
- License: Apache-2.0 (verified 2026-05-17)
- EYEX use today: runtime dependency. PP-OCRv5 server ONNX runs on DirectML for line/cell text recognition; PP-StructureV3 provides layout/table/reading-order parsing. Routing lives in `config/ocr_profiles/windows_radeon_balanced.yaml` and `backend/app/services/ocr_engine/engines/`.
- Reference borrowing: layered pipeline pattern (layout / table / OCR as separate stages with canonical merge), profile-keyed engine selection, source-page-pixel coordinate system. Documented in `docs/OCR_UPGRADE.md` and `docs/DECISIONS.md` 2026-05-01 "Strong OCR is layout-led canonical merging".
- Boundary: model files materialize under `var/models/`; engine selection and accelerator policy live in YAML, not Python branches.

### MinerU 2.5 (1.2B two-stage VLM)

- Upstream: [github.com/opendatalab/MinerU](https://github.com/opendatalab/MinerU)
- License: MinerU Open Source License, based on Apache-2.0 with additional conditions (verified 2026-05-17)
- EYEX use today: design reference only. Not a runtime dependency.
- Reference borrowing: two-stage parsing (downsampled global layout analysis followed by native-resolution content recognition for text, formulas, tables) is a useful contrast to EYEX's canonical merge approach. The "global layout first, fine-grained recognition second" idea is captured in the canonical merge ordering used by `ocr_engine/canonicalize.py`.
- Boundary: any source-level reuse is explicitly blocked until a `docs/DECISIONS.md` entry resolves the additional license conditions and confirms compatibility with personal-use distribution. Treat as ideas-only reference.

### Docling (IBM Deep Search)

- Upstream: [github.com/docling-project/docling](https://github.com/docling-project/docling)
- Companion: [docling-core](https://github.com/docling-project/docling-core), [docling-serve](https://github.com/docling-project/docling-serve)
- License: MIT (verified 2026-05-17)
- EYEX use today: planned offline OCR evaluation engine, not a default runtime stage. The PLAN task "Add Docling as offline OCR eval second source" tracks integration through `.venv-ocr` and `scripts/run-ocr-eval.py --engine docling`.
- Reference borrowing: the unified document data model (DoclingDocument with body, tables, lists, captions, picture annotations) is a useful comparison to `DocumentIR`. The reading-order graph traversal and table-cell graph patterns are studied for the OCR canonical merge boundary task tracked in PLAN.
- Boundary: avoid pulling Docling's heavy dependency tree (PyTorch, transformers, layout/table models) into the main backend `requirements.txt`. The runtime path stays PaddleOCR-only; Docling lives in `.venv-ocr` for eval.

### olmOCR / olmOCR 2 (Allen AI)

- Upstream: [github.com/allenai/olmocr](https://github.com/allenai/olmocr)
- Model: [allenai/olmOCR-2-7B-1025](https://huggingface.co/allenai/olmOCR-2-7B-1025) (a Qwen2.5-VL-7B fine-tune trained with reinforcement learning from verifiable unit-test rewards, RLVR)
- License: Apache-2.0 (verified 2026-05-17)
- EYEX use today: design reference only. Not a runtime dependency.
- Reference borrowing: the RLVR-with-unit-tests training recipe is the most relevant idea for EYEX precision work. Each medical extraction field can be expressed as a deterministic unit test (allowed code, evidence span verbatim in DocumentIR, no forbidden inference flags). This pattern is referenced in `docs/ROADMAP.md` for the precision evaluation harness rather than for model training.
- Boundary: EYEX does not train or fine-tune VLMs. The borrowing is the verification harness pattern, not the model.

### Marker

- Upstream: [github.com/datalab-to/marker](https://github.com/datalab-to/marker)
- License: GPL-3.0 (verified 2026-05-17)
- EYEX use today: design reference only. Not a runtime dependency.
- Reference borrowing: the layout block taxonomy and the table-cell reconstruction pipeline are well-documented references when reasoning about the `ocr_engine` vs `layout_normalizer` boundary.
- Boundary: GPL-3.0 is incompatible with EYEX's intended distribution model. Source-level reuse is not allowed without a `docs/DECISIONS.md` entry that documents the implications. Treat as ideas-only reference; do not paste, port, or adapter-vendor Marker source.

### dots.ocr (rednote-hilab)

- Upstream: [github.com/rednote-hilab/dots.ocr](https://github.com/rednote-hilab/dots.ocr)
- License: Apache-2.0 (verified 2026-05-17)
- EYEX use today: design reference only. Not a runtime dependency.
- Reference borrowing: the unified-VLM-for-layout-and-text design (1.7B parameters covering layout detection plus content recognition in one pass) is a useful contrast to EYEX's multi-stage layout-led pipeline. The reading-order recovery on multilingual documents is studied for `canonicalize.py` ordering decisions.
- Boundary: EYEX does not bundle 1.7B-class VLMs in the default install. Any future integration would belong in `.venv-ocr` and not in the main backend dependency set.

### Unstructured

- Upstream: [github.com/Unstructured-IO/unstructured](https://github.com/Unstructured-IO/unstructured)
- License: Apache-2.0 (verified 2026-05-17)
- EYEX use today: design reference only.
- Reference borrowing: the element-type taxonomy (Title, NarrativeText, ListItem, Table, FigureCaption, Header, Footer) maps cleanly to `DocumentIRBlock.block_type` and `DocumentIRBlock.document_region`. The chunk strategies inform the evidence-pack windowing in `services/evidence.py`.
- Boundary: avoid pulling Unstructured's broad dependency surface. Use it as a vocabulary reference, not a library.

## LLM Routing and Structured Outputs

### Instructor

- Upstream: [github.com/instructor-ai/instructor](https://github.com/instructor-ai/instructor)
- License: MIT (verified 2026-05-17)
- EYEX use today: design reference only. Not a runtime dependency.
- Reference borrowing: the validate-and-retry loop on Pydantic models is the closest external analog to EYEX's `provider.verify_against_document`. The retry budget and validation-error feedback patterns inform the LLM router error-classification logic in `services/llm_provider/fallback.py`.
- Boundary: EYEX prefers OpenAI Responses' strict JSON Schema mode and DeepSeek's `response_format=json_object` for cost-cache stability rather than client-side validate-and-retry. Instructor patterns are referenced when designing offline retry policies for ConservativeLocalProvider, not as a runtime dependency.

### Outlines

- Upstream: [github.com/dottxt-ai/outlines](https://github.com/dottxt-ai/outlines)
- License: Apache-2.0 (verified 2026-05-17)
- EYEX use today: design reference only. Not a runtime dependency.
- Reference borrowing: token-level constrained generation through finite-state masks is the strongest available technique for guaranteeing schema compliance. Useful as a comparison when arguing that hosted Structured Outputs from OpenAI / DeepSeek are sufficient for current EYEX field schemas.
- Boundary: Outlines requires a self-hosted inference engine (vLLM, transformers) to apply token masks. EYEX runs against hosted APIs. Adoption is gated on a future local-LLM scenario.

### LiteLLM

- Upstream: [github.com/BerriAI/litellm](https://github.com/BerriAI/litellm)
- License: MIT for the core (`litellm/`); Enterprise add-ons are separately licensed (verified 2026-05-17)
- EYEX use today: design reference only. Not a runtime dependency.
- Reference borrowing: the Router (model alias, fallbacks, retries, cost tracking, key cooldown) and the unified provider façade are the most directly applicable patterns for EYEX's `services/llm_provider/`. The provider-protocol classification (chat-completions-compatible vs Anthropic-messages vs Google-Gemini vs OpenAI-Responses) maps onto EYEX's adapter split.
- Caution: LiteLLM had a public PyPI compromise in 2026-03 (issue #24518). Per the AGENTS.md Dependency Management rule, EYEX cannot add LiteLLM as a runtime dependency without a documented post-incident remediation note from the upstream. If adopted later, it would be as a sidecar with pinned image digest and isolated credentials, not a Python dependency.
- Boundary: borrow patterns by hand-rolling adapters in `services/llm_provider/` rather than importing.

### Continue

- Upstream: [github.com/continuedev/continue](https://github.com/continuedev/continue)
- License: Apache-2.0 (verified 2026-05-17)
- EYEX use today: design reference only.
- Reference borrowing: the `config.yaml` model definition format (model id, capabilities, headers, requestOptions, roles) informs `config/model_profiles/*.yaml` and `config/model_providers/*.yaml`. The capability flags (`json_schema`, `json_object`, `vision`, `prompt_cache`, `reasoning_effort`) shape the EYEX provider catalog schema.
- Boundary: Continue is an IDE agent, not an extraction backend. Borrow the config schema, not the runtime.

### OpenClaw

- Upstream: [docs.openclaw.ai/models](https://docs.openclaw.ai/models)
- License: MIT for the published source (per `THIRD_PARTY_NOTICES.md`)
- EYEX use today: design reference. The provider catalog separation between catalog metadata, auth profile, and model binding is adapted from OpenClaw's documented pattern. No source files are vendored.
- Reference borrowing: `provider/model` reference shape, separation of credentials from model bindings, primary-plus-fallback chain, generated `models.json` style separation. Already documented in `docs/LLM_PROVIDER_ALIGNMENT.md` and `THIRD_PARTY_NOTICES.md`.
- Boundary: do not copy OAuth flow code; EYEX prefers API-key-with-cooldown and is not an IDE agent.

### Cline

- Upstream: [github.com/cline/cline](https://github.com/cline/cline)
- License: Apache-2.0
- EYEX use today: design reference only.
- Reference borrowing: provider-agnostic OAuth-or-BYOK-or-local entry pattern; using OS credential store for keys; provider type, model capability, and settings UI separation. Captured in `docs/LLM_PROVIDER_ALIGNMENT.md`.
- Boundary: VS Code SecretStorage code does not port to FastAPI. The borrowing is the layering, not the implementation.

### Open WebUI

- Upstream: [github.com/open-webui/open-webui](https://github.com/open-webui/open-webui)
- License: Open WebUI License with brand restrictions
- EYEX use today: design reference only.
- Reference borrowing: protocol-oriented design (prefer standard protocols, route non-standard providers through proxy/pipe); allow manual model allowlist when `/models` discovery fails. Captured in `docs/LLM_PROVIDER_ALIGNMENT.md`.
- Boundary: the brand-restricted license prevents source-level reuse. Treat as ideas-only.

### Dify

- Upstream: [github.com/langgenius/dify](https://github.com/langgenius/dify)
- License: Modified Apache-2.0 with multi-tenant and brand restrictions
- EYEX use today: design reference only.
- Reference borrowing: provider plugin schema (provider YAML plus credential schema plus `validate_provider_credentials`); coexistence of preset and custom models. Captured in `docs/LLM_PROVIDER_ALIGNMENT.md`.
- Boundary: license restrictions prevent source-level reuse. Treat as ideas-only.

## Local Borrowing and Source Copies

When EYEX adopts source-level reuse from any of the projects above, the change must:

1. Land the copy in a clearly named adapter directory under `backend/app/` (for example `backend/app/services/llm_provider/<vendor>/` or `backend/app/services/ocr_engine/<vendor>/`).
2. Preserve the upstream `LICENSE` and `NOTICE` files in that directory.
3. Retain copyright headers in copied source files.
4. Add an entry to `THIRD_PARTY_NOTICES.md` describing scope, version pinned (commit SHA), and local modifications.
5. Reference the corresponding `docs/DECISIONS.md` entry that approved the copy and resolved any non-MIT/Apache/BSD license question.

For shallow study clones used for read-only research, the location is `references/` (gitignored). Use `--depth=1` and never import from this path. The `governance-foundation` change in `docs/DECISIONS.md` 2026-05-17 records the policy.

## Re-verification Checklist

Before adding or extending an entry in this file, run these checks against the upstream:

- License URL still matches the recorded license. Some projects have changed (for example marker moved between maintainers; verify the active fork's license, not historical forks).
- Upstream is still maintained (a release or merged PR within the past year).
- No public supply-chain incident in the last 12 months without a documented post-incident remediation note. The LiteLLM 2026-03 PyPI compromise is the canonical reason this check exists.
- Commit-pinned URLs in linked decisions or code adapters still resolve.

The next session that touches this file is expected to re-run these checks for the entries it modifies.
