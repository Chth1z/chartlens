# OCR Post-Processing Notes

This document maps the open-source landscape for **post-OCR text correction and clinical normalization in Chinese medical records** to EYEX's current pipeline. It is reference research for future precision tasks; nothing here is a runtime dependency yet.

License notes were checked against upstream URLs on 2026-05-18. Re-verify before any source-level reuse, per `AGENTS.md` Reference Projects Policy.

## Where Post-Processing Fits in EYEX Today

EYEX's pipeline already separates raw OCR from normalized DocumentIR (see `docs/ARCHITECTURE.md`, decision 2026-05-01 "Layout normalization separates raw OCR from extraction IR"):

```text
Raw OCR blocks  ->  layout_normalizer (screen chrome removal,
                    paragraph reflow, key-value derivation)
                ->  deidentify_document_ir (PHI redaction)
                ->  DocumentContext  ->  evidence_first / LLM
```

The places where post-processing techniques would slot in:

1. **Character-level OCR correction** — between `ocr_engine` canonical merge and `layout_normalizer`. Today there is no character-level correction step. OCR confidence below profile thresholds simply triggers re-routing to a stronger engine; misrecognized characters that pass the threshold flow through unchanged.
2. **Medical entity normalization** — inside or alongside `evidence_first`. Today, field synonyms are flat YAML lists (`hypertension_history.synonyms = [高血压, 高血压病, 血压升高]`). Real EMR variation (`血压偏高`, `血压增高`, `BP高`) is not captured.
3. **Table structure recovery** — partly covered by `ocr_engine/canonicalize.py:recover_grid_table_cells` and PP-StructureV3 layout output. Stronger table recovery would benefit `aneurysm_location`, score grades, and timeline fields where the source is tabular.
4. **Reading order / clause segmentation** — partly covered by `merge_policy_version: ocr-canonical-layout-v3` and the new clause-boundary clip in `_positive_span` (commit `fdaed1c`). Stronger clause segmentation would reduce false-negative recall for evidence-first extraction.

The four buckets below are organized by which slot they target.

## Bucket 1 — Character-Level OCR Correction

### pycorrector (shibing624)

- Upstream: [github.com/shibing624/pycorrector](https://github.com/shibing624/pycorrector)
- License: Apache-2.0 (verified 2026-05-18)
- What it does: Chinese spelling correction with multiple backends — n-gram + pinyin/shape similarity, MacBERT4CSC, Qwen-based corrector models, and an ChineseErrorCorrector3-4B (Qwen3-4B fine-tune) that the upstream repo claims SOTA on CSC and CGC tasks.
- Fit for EYEX: **medium**. The pinyin/shape correctors are a real fit for OCR character substitutions (e.g. `胆` ↔ `担`, `盐` ↔ `炎`). The 4B Qwen corrector is too heavy for the current `.venv-ocr` runtime budget on Radeon DirectML.
- Recommended: borrow the **n-gram + pinyin/shape rule layer only** as design reference. Implementing it directly inside `services/layout_normalizer.py` as a small confidence-gated hook is preferable to vendoring the package, because pycorrector pulls heavy NLP deps (jieba, kenlm, transformers) that bloat the backend `requirements.txt`.
- Alternative: adopt the **dictionary-augmented Symspell** approach (a well-known design in English OCR, transferable to Chinese with character-level edit distance) using a custom medical-term dictionary. Lightweight, no model load.

### ChineseErrorCorrector3-4B (paper)

- Upstream: [arxiv.org/abs/2511.17562](https://arxiv.org/abs/2511.17562) "State-of-the-Art Chinese Spelling and Grammar Corrector" (2025-11)
- License of the paper: arXiv non-exclusive license; weights are MIT or Apache (verify on the model card before any vendoring).
- What it does: Qwen3-4B fine-tune that beats prior CSC/CGC SOTA. The paper reports gains specifically on real-world noisy text including OCR output.
- Fit for EYEX: **low for the runtime path, high for the eval path**. 4B parameter inference at single-page latency is incompatible with EYEX's "single-field evidence-first extraction P95 ≤ 6 s" target on the reference RX 6600 workstation. But running it offline against a sample of OCR output to **measure** how much character-level error remains after canonical merge would be a useful diagnostic.
- Recommended: optional eval-only sidecar, in `.venv-ocr`. Use it to produce a "what fraction of characters in current OCR output would be flipped by a SOTA corrector?" report that informs whether to invest more effort in this bucket.

### PERL — Pinyin Enhanced Rephrasing Language Model

- Upstream: [arxiv.org/abs/2412.03230](https://arxiv.org/abs/2412.03230) (2024)
- License: paper only; reference implementation availability varies by author.
- What it does: predicts the correct length of corrected output and uses pinyin embeddings for phonetically similar substitutions. Designed for ASR N-best correction; the pattern transfers to OCR top-k recognition output.
- Fit for EYEX: **low for now**. EYEX's current OCR adapter does not surface top-k character candidates from PP-OCRv5 ONNX; it returns the argmax line. Without N-best the technique is reduced to pinyin-based dictionary lookup, which is already covered by the pycorrector path above.
- Recommended: park. Revisit only if EYEX adds a top-k recognition path.

## Bucket 2 — Medical Entity Normalization

### CBLUE — Chinese Biomedical Language Understanding Evaluation

- Upstream: [github.com/CBLUEbenchmark/CBLUE](https://github.com/CBLUEbenchmark/CBLUE)
- License: Apache-2.0 for the benchmark code (verified 2026-05-18); individual datasets carry their own redistribution terms — must check per dataset.
- What it does: 8 medical NLP tasks including CHIP-CDN (clinical diagnosis normalization), CHIP-MDCFNPC (medical event extraction), and CMeEE (entity recognition). The dataset structure and the published baseline metrics are useful as a reference for how Chinese clinical NLP is benchmarked.
- Fit for EYEX: **high as a reference**, low as a runtime dependency. EYEX is field-targeted extraction with an evidence contract; CBLUE tasks are general NLU. But the **CHIP-CDN diagnosis normalization mapping** is the closest open-source analog to EYEX's field synonym lists, and its data shape (input mention → ICD code) mirrors what EYEX would need if it ever lifted `aneurysm_location` synonym handling from flat lists to a normalization model.
- Recommended: borrow the **mapping-table format** for the medical synonym dictionary (next bucket). Do not adopt the BERT-based CDN baseline as runtime dependency — too heavy for the local pipeline and the precision contract; revisit if a local LLM fallback path lands (`ROADMAP E2-006`).

### PromptCBLUE

- Upstream: [github.com/michael-wzhu/PromptCBLUE](https://github.com/michael-wzhu/PromptCBLUE)
- License: Apache-2.0 (verified 2026-05-18)
- What it does: instruction-tuning dataset that wraps CBLUE tasks as prompts, useful for evaluating LLM-based medical NLP.
- Fit for EYEX: **medium**. Provides ready-made instruction data for LLM fine-tuning or in-context learning evaluation. EYEX is moving toward evidence-first prompting (ROADMAP E1-001), and PromptCBLUE's CHIP-CDN style prompts are a useful template for how to phrase a "normalize this Chinese clinical mention to ICD/SNOMED-CT" sub-task inside the evidence-first flow.
- Recommended: study only. Use as design reference when expanding evidence-first prompts.

### SNOMED CT with Chinese synonyms enrichment (SCCSE)

- Reference paper: [bmcmedinformdecismak.biomedcentral.com/articles/10.1186/s12911-017-0455-z](https://bmcmedinformdecismak.biomedcentral.com/articles/10.1186/s12911-017-0455-z) "Enriching the international clinical nomenclature with Chinese daily used synonyms"
- License: SNOMED CT itself requires an IHTSDO affiliate license for production use; the synonym data may have separate terms.
- What it does: maps daily-used Chinese clinical phrases (the kind that match "血压偏高" rather than "高血压病") to SNOMED CT concept IDs.
- Fit for EYEX: **strategically high, operationally blocked**. SNOMED CT licensing is incompatible with EYEX's "MIT / Apache / BSD by default" reference policy without an explicit `docs/DECISIONS.md` entry that confirms the user has the affiliate license.
- Recommended: park unless the user obtains an IHTSDO affiliate license. Use ICD-10-CN (Chinese national classification) as the open alternative; cross-mapping resources between ICD-10-CN and SNOMED-CT exist but most are paywalled.

### Medical-Spell-Corrector (skshashankkumar41)

- Upstream: [github.com/skshashankkumar41/Medical-Spell-Corrector](https://github.com/skshashankkumar41/Medical-Spell-Corrector)
- License: not specified in the README on the verification date; treat as "all rights reserved" until a LICENSE file is added.
- What it does: small spell corrector with a hand-curated medical word list (English).
- Fit for EYEX: **none directly** (English-only). The data structure (word frequency dictionary + edit distance) is the same Symspell pattern referenced above.
- Recommended: skip.

## Bucket 3 — Table Structure Recovery

### PaddleOCR PP-StructureV3 (already runtime)

- Upstream: [github.com/PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
- License: Apache-2.0
- Status in EYEX: runtime stage in `windows_radeon_balanced` profile. See `config/ocr_profiles/windows_radeon_balanced.yaml` and `services/ocr_engine/engines/paddle_structure_v3.py`.
- Recommended improvement (in scope for ROADMAP E0-005 split): currently `ocr_engine/canonicalize.py:recover_grid_table_cells` does a generic "infer grid from bbox clusters" reconstruction when the engine emits no `block_type=cell`. After the E0-005 split lands, PP-StructureV3 cell output should flow directly into `layout_normalizer.py` and the recovery heuristic can be tightened against PP-StructureV3 ground truth.

### MinerU 2.5 / Docling reading-order graph

- Upstreams listed in `docs/REFERENCE_PROJECTS.md` with license caveats (MinerU OSL with additional terms, Docling MIT).
- What they do: explicit reading-order graphs and table-cell graphs that EYEX's flat reading_order integer cannot represent. Docling's `DoclingDocument` is the strongest open analog; its table cells carry both row/col coordinates and a content reference.
- Fit for EYEX: **high as design reference**. Already named in `docs/REFERENCE_PROJECTS.md` E1-007 (Docling as offline OCR eval second source). Adopting the data shape would let `aneurysm_location` evidence pin a specific table cell instead of a paragraph snippet.
- Recommended: when ROADMAP E1-004 (layout-aware evidence pack windowing) lands, adopt Docling's element-type vocabulary by reference (no source copy) for naming new `DocumentIRBlock.document_region` values.

## Bucket 4 — Reading Order and Clause Segmentation

### Block-based reading order detection (ROD)

- Reference paper: [link.springer.com/article/10.1007/s11042-025-20736-y](https://link.springer.com/article/10.1007/s11042-025-20736-y) "Detecting reading orders with block-based models for OCR for classical Chinese documents" (2025-03)
- What it does: rule-based + n-gram model for ROD; targets classical Chinese vertical text but the same algorithm applies to any Chinese text where bbox geometry is the primary signal.
- Fit for EYEX: **already matched**. Decision 2026-05-05 "OCR merge policy v2 uses visual order before raw reading order" implements the same principle: bbox geometry is the final ordering guard, raw engine `reading_order` is only fallback. The paper is a useful citation for that decision but does not introduce new technique.
- Recommended: cite from `docs/DECISIONS.md` 2026-05-05 entry on the next edit pass for that decision.

### Sentence terminator clause clipping (already in EYEX)

- Status: decision 2026-05-17 "mock_general accuracy raised to 1.0 via clause-boundary positive span fix" describes EYEX's own implementation. The technique — clip at `。 ； ; \n` and only trust same-clause negation — is documented at `services/evidence_first.py:_positive_span` and `_negative_span`.
- Recommended improvement (next E1 task): widen the terminator set to include Chinese parens (`（）`), spaced bullets, and table-cell separators when the surrounding block is a `key_value`. This is internal work, no upstream borrow needed.

## Operational Recommendations

Roadmap mapping (one-line summary per bucket):

- **Bucket 1 character correction**: not in default runtime; run `pycorrector` n-gram + pinyin pass as **eval-only diagnostic** to measure how much OCR character noise actually reaches the extractor. This becomes a new `ROADMAP E1-009` candidate. License: Apache-2.0, low risk.
- **Bucket 2 medical normalization**: extend the schema's flat `synonyms` list into a per-field synonym table that supports both string variants (`高血压`, `血压偏高`, `血压增高`, `BP高`) and a mapping to a canonical clinical concept (`hypertension`). Build this table by hand, seeded from CBLUE CHIP-CDN / ICD-10-CN keywords. **Do not** vendor SNOMED CT. Becomes the next iteration of `ROADMAP E1-005` (synonym widening).
- **Bucket 3 table recovery**: continue tracking through `ROADMAP E0-005` (engine vs normalizer split) and `ROADMAP E1-004` (layout-aware evidence pack windowing). No new task needed.
- **Bucket 4 reading order / clauses**: incremental improvement inside `services/evidence_first.py` and `services/layout_normalizer.py`. No new task needed; the next clause-boundary fix would be a follow-up to the 2026-05-17 decision.

## What This Means for the Mock Baseline

The `mock_general` baseline gap (`52/54`) is dominated by **bucket 2** issues (medical synonym variation). Closing them via ROADMAP E1-005 synonym widening is the cheapest, lowest-risk path. The other three buckets are real but not currently the bottleneck on the synthetic fixtures.

The bottleneck order changes when the baseline switches to real de-identified scans (ROADMAP E2-001 / E2-002):

- Bucket 1 (character correction) becomes the first noise source.
- Bucket 3 (table recovery) becomes the dominant accuracy floor for `aneurysm_location`, score grades, and timeline.
- Bucket 4 (reading order) becomes the dominant accuracy floor for paragraphs that span pages or got reordered by tile-based OCR.
- Bucket 2 normalization stays a long-tail issue throughout.

The plan therefore is: keep tightening synonyms while the baseline is synthetic, and prepare bucket 1 + 3 + 4 design references for the moment a real corpus lands.
