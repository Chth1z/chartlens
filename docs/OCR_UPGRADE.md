# OCR Upgrade Notes

## Current Decision

PaddleOCR-VL is temporarily parked outside the default EYEX OCR route.

The default single-machine Windows Radeon route is now:

```text
native PDF text
  -> local OCR sidecar
  -> PP-StructureV3 layout/table parsing when available
  -> PP-OCRv5 server ONNX on ONNX Runtime DirectML
  -> backend canonical DocumentIR merge
```

EYEX no longer installs Docker Desktop, starts ROCm containers, downloads
PaddleOCR-VL images, or reads `EYEX_OCR_PADDLEOCR_VL_URL` as a runtime route.
The installer still clears that environment value so stale `.env` settings do
not keep the frontend in a "VL sidecar missing" state.
The sidecar also no longer accepts `EYEX_OCR_SIDECAR_ENGINES`; engine order is
owned only by the active OCR profile under `config/ocr_profiles/`.

Reason:

- The target workstation is Windows with an AMD Radeon RX 6600. The stable GPU
  path is PP-OCRv5 ONNX through ONNX Runtime DirectML.
- The attempted official AMD/ROCm Docker sidecar pulled very large images and
  failed in the local Docker/WSL device layer. Keeping it in the default route
  makes setup fragile.
- Running PaddleOCR-VL on local CPU can exhaust memory and freeze the machine.
- Reimplementing PaddleOCR-VL through DirectML/ONNX would require owning
  tokenizer handling, image preprocessing, autoregressive generation,
  postprocessing, bbox recovery, and Markdown/layout reconstruction. That is not
  a safe production shortcut.

## Public Commands

Use only the root commands for normal operation:

```powershell
.\install-ocr.cmd
.\start.cmd
.\stop.cmd
```

`install-ocr.cmd` is fully automatic by default. It:

1. Detects the GPU route.
2. Creates or reuses `.venv-ocr`.
3. Installs the OCR sidecar dependencies.
4. Prepares project-local PP-OCRv5 server ONNX files under
   `var\models\ppocrv5-directml-server`.
5. Validates ONNX Runtime DirectML with `DmlExecutionProvider`.
6. Writes `.env` values for the local OCR sidecar.
7. Starts EYEX through `start.cmd` unless `-NoStartSidecar` is passed.

The installer must not write model, cache, or temp files outside the project.
Runtime and model state belongs under `var/`.

## GPU Policy

Supported default routes:

- NVIDIA with `nvidia-smi`: CUDA Paddle route.
- AMD Radeon or other Windows GPU: `windows_radeon_balanced` with PP-OCRv5
  server ONNX on DirectML.
- Explicit CPU fallback: `-GpuPolicy Off`.

The AMD route does not try to guarantee PaddleOCR-VL GPU execution. It
guarantees the local PP-OCRv5 DirectML path and keeps layout/table parsing
separate from any remote VLM experiment.

## Execution Safety

The OCR orchestrator now treats each engine attempt as a bounded stage:

- backend intelligent OCR wraps each engine call with a timeout guard;
- local OCR sidecar does the same before accepting the result;
- both paths emit `ocr_trace` metadata with stage status, duration, and
  page-level quality summaries;
- engine timeouts are marked as `PAGE_TIMEOUT` and fall through to the next
  candidate engine instead of retrying the same stuck workload.

This follows the same general discipline used by mature OCR systems: timing and
failure boundaries belong inside the OCR pipeline, not only at the HTTP layer.

## Regression Eval

EYEX now includes a versioned OCR regression entrypoint:

```powershell
.\scripts\run-ocr-eval.ps1 -ProfileId mock_general
```

The PowerShell wrapper uses `.venv-ocr\Scripts\python.exe` automatically when
that project OCR runtime exists. Pass `-PythonExe ...` only when intentionally
running with another Python.

OCR regression profiles live under `config\ocr_evaluation_profiles\`. Each case
declares a versioned document path plus page-level ground truth text. The
runner builds `DocumentIR`, compares OCR output with weighted CER/WER, and
reports the resolved OCR engine, page results, layout/table metrics, and any
`ocr_trace` metadata captured during the run. The report also includes an
`environment` section with DirectML/CUDA/ROCm probe evidence, per-target
readiness, OCR sidecar preflight status, and copyable follow-up commands.

When `EYEX_OCR_DOCUMENT_AI_URL` points at the local sidecar, the runner first
checks the sidecar `/health` contract. It blocks before processing cases if the
running sidecar does not report `api_contract_version=eyex-ocr-sidecar-v2` or
the current `ocr-canonical-layout-v3` merge policy. This prevents stale sidecar
processes from making eval output look worse than the checked-out code.

For the verified local AMD/DirectML path without any currently running sidecar,
clear the sidecar URL only for the eval process:

```powershell
$env:EYEX_OCR_DOCUMENT_AI_URL=''
.\scripts\run-ocr-eval.ps1 -ProfileId synthetic_medical_directml
```

If the preflight reports a stale sidecar, restart only through the existing root
scripts so EYEX-owned processes are stopped and restarted consistently:

```powershell
.\stop.cmd
.\start.cmd
.\scripts\run-ocr-eval.ps1 -ProfileId synthetic_medical_directml
```

When `truth_blocks` are present, the runner reports `layout_metrics`:
block text match accuracy, bbox IoU accuracy, center-position accuracy, and
reading-order accuracy. When `truth_tables` are present, it reports
`table_metrics`: cell text accuracy, row/column key preservation accuracy, and
cell bbox accuracy. Summary averages are `null` until a profile has the
corresponding truth annotations.

The repository profile `mock_general` is intentionally lightweight and CI-safe.
It proves the OCR regression harness works without requiring heavy local OCR
dependencies. Real medical OCR optimization should extend
`medical_inpatient_zh.yaml` with de-identified fixture documents and truth text.

For real hardware profiles, each case must include:

- `document_path`: de-identified image or PDF fixture committed under
  `config\ocr_evaluation_profiles\fixtures\` or another versioned config path.
- `truth_pages`: exact page text in expected reading order.
- `truth_blocks`: block-level annotations with `page`, `reading_order`, `text`,
  and four-number `bbox`.
- `truth_tables`: table annotations with `cells`, where every cell has `row`,
  `col`, `text`, and four-number `bbox`; include `row_span` or `col_span` when
  source cells are merged.
- `tags`: accelerator/document slices such as `directml`, `cuda`,
  `rocm_remote`, `table`, `paragraph`, and `multi_page`.

Use the checked-in manifest template as the starting point:

```powershell
.\scripts\run-ocr-eval.ps1 -ProfileId real_hardware_case_template -AllowEmptyHardwareProfile
```

That profile is marked `template: true`, so running it returns a blocked
template report instead of trying to open placeholder files. Without
`-AllowEmptyHardwareProfile`, any hard blocker, including a template profile,
missing real corpus, unreachable configured sidecar, or stale sidecar contract,
exits non-zero so CI and future hardware runs cannot silently pass. Copy the
case shape from `config\ocr_evaluation_profiles\real_hardware_case_template.yaml`
into `medical_inpatient_zh.yaml` only after replacing every placeholder document
and annotation with reviewed de-identified truth.

Minimal case shape:

```yaml
cases:
  - case_id: deid-case-001
    document_path: fixtures/deid-case-001.pdf
    tags: [directml, cuda, table, paragraph]
    truth_pages:
      1: |
        基本信息：患者，男，66岁。
        检验项目 白细胞 8.6
    truth_blocks:
      - page: 1
        reading_order: 1
        text: 基本信息：患者，男，66岁。
        bbox: [120, 90, 860, 128]
      - page: 1
        reading_order: 2
        text: 白细胞
        bbox: [120, 180, 220, 210]
    truth_tables:
      - table_id: t1
        page: 1
        cells:
          - row: 1
            col: 1
            text: 检验项目
            bbox: [120, 150, 220, 178]
          - row: 2
            col: 1
            text: 白细胞
            bbox: [120, 180, 220, 210]
          - row: 2
            col: 2
            text: "8.6"
            bbox: [240, 180, 300, 210]
```

`medical_inpatient_zh` is intentionally blocked until a real de-identified OCR
corpus and hardware route are available. Its profile declares
`requires_real_hardware: true`, `requires_deidentified_corpus: true`, at least 5
cases, and target accelerators `directml`, `cuda`, and `rocm_remote`. Running it
without fixtures exits non-zero by default:

```powershell
.\scripts\run-ocr-eval.ps1 -ProfileId medical_inpatient_zh
```

Use `-AllowEmptyHardwareProfile` only when you want to print the blocker report
without treating the blocked profile as a passing eval. This is report-only
mode for documenting missing hardware/corpus/preflight states, not a success
condition.

## Runtime Readiness

`/api/settings/runtime` is the frontend contract for startup state. It reports:

- local OCR sidecar connection status;
- active OCR profile and pipeline stages;
- PP-OCRv5 DirectML readiness;
- PP-StructureV3 readiness when required by the active profile;
- repair actions limited to `.\stop.cmd`, `.\start.cmd`, and
  `.\install-ocr.cmd`.

If a stale sidecar or `.env` still reports PaddleOCR-VL/ROCm, the UI should
treat it as an old configuration residue and ask for reinstall/restart of the
local OCR route, not for manual VL sidecar setup.

The current local sidecar `/health` response must include
`api_contract_version: eyex-ocr-sidecar-v2` and an `ocr_profile` payload whose
`merge_policy_version` is `ocr-canonical-layout-v3` for the DirectML/CUDA
canonical routes. Backend runtime diagnostics, OCR eval preflight, and the HTTP
OCR adapter reject local sidecars missing the contract and report: restart EYEX
with `.\stop.cmd` followed by `.\start.cmd`. Known pre-fix NumPy parser failures
from an old sidecar response are also classified as restart-required instead of
ordinary OCR quality failures.

## Model And Cache Locations

- Models: `var\models\...`
- Install-time caches: `var\cache\ocr-install\...`
- Runtime caches: `var\cache\ocr-runtime\...`
- Source page images/debug artifacts: `var\...`

The installer sets `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `PIP_CACHE_DIR`,
`PADDLE_HOME`, `PADDLEOCR_HOME`, `PADDLEX_HOME`, `XDG_CACHE_HOME`,
`PADDLE_PDX_CACHE_HOME`, and `TORCH_HOME` to project-local paths before package
installation or model preparation.

## Open-Source Components

| Project | EYEX use |
| --- | --- |
| PP-OCRv5 server | Default Windows GPU text recognizer through ONNX Runtime DirectML. |
| PP-StructureV3 | Layout/table parser for canonical merge and table-aware evidence. |
| PaddleOCR-VL | Parked experiment only; not part of default install/start/runtime route. |
| Docling/Marker/MinerU/Unstructured | Offline evaluation candidates, not default runtime dependencies. |

Primary references:

- https://www.paddleocr.ai/main/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html
- https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-StructureV3/PP-StructureV3.html
- https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html
- https://www.paddleocr.ai/main/en/version3.x/algorithm/PaddleOCR-VL/PaddleOCR-VL.html
- https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PaddleOCR-VL-AMD-GPU.html

## Revisit Conditions

Revisit PaddleOCR-VL only when one of these is true:

- a maintained DirectML/WebGPU/Windows adapter exists and passes EYEX OCR evals;
- a supported ROCm host is available and runs the official service reliably;
- a packaged installer can manage Docker/WSL/ROCm as a declared prerequisite
  without breaking the one-click local setup.

Until then, OCR accuracy work should focus on DirectML PP-OCRv5, PP-StructureV3
layout/table extraction, preprocessing candidates, canonical merge quality, and
debug/eval tooling.
