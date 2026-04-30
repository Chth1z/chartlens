# OCR Upgrade Notes

## Recommendation

EYEX now treats OCR as an intelligent-document engine chain, not as a single
`image -> text` helper. The default route is:

```text
native PDF text
  -> intelligent document engines
  -> fail fast when no intelligent engine is available
```

The old page-render/preprocess fallback has been removed. RapidOCR is used only
for the Windows DirectML PP-OCRv5 ONNX route. If the HTTP document-intelligence
sidecar, OpenAI vision document parser, PP-OCRv5 DirectML, PaddleOCR-VL,
PP-StructureV3, or Docling are unavailable, EYEX stops OCR with an explicit
`OCR_ENGINE_UNAVAILABLE` error so the frontend can show the missing engine state
and the concrete unavailable reasons.

Reason:

- The current app runs on Windows with Python 3.14. PaddleOCR-VL documents Python 3.9-3.13 as the verified manual-install range, so heavy OCR should run in a dedicated runtime or container.
- Medical files are sensitive. A local sidecar keeps data on the machine and lets us pin a separate runtime without destabilizing the API server.
- `test2.pdf` is an image-PDF with embedded screenshots, moire, skew, and forms. It benefits first from image extraction, crop, preprocessing, and layout-aware parsing.

## Current implementation

- `backend/app/services/intelligent_ocr.py` defines the adapter contract.
- `backend/app/services/ocr.py` routes image PDFs/images through intelligent OCR only.
- `backend/ocr_sidecar/main.py` exposes the local OCR sidecar `POST /extract` API.
- `scripts/install-intelligent-ocr.ps1` creates the OCR runtime and configures `.env`.
- `backend/app/core/settings.py` controls routing:
  - `EYEX_OCR_STRATEGY=intelligent`
  - `EYEX_OCR_PROFILE=windows_radeon_balanced`
  - OCR engine order is versioned in `config/ocr_profiles/*.yaml`
  - `EYEX_OCR_DOCUMENT_AI_URL=` for a local/intranet sidecar service
  - `EYEX_OCR_DOCUMENT_AI_TIMEOUT_SECONDS=900` for CPU-sidecar OCR requests
  - `EYEX_OCR_SIDECAR_ENGINES=` for optional sidecar-local engine selection
  - `EYEX_OCR_ACCELERATOR=auto|cpu|cuda|rocm|directml|remote` for accelerator preference
  - `EYEX_OCR_DEVICE=cpu` or `gpu` remains as a legacy Paddle device fallback
  - `EYEX_OCR_DIRECTML_MODEL_DIR=` for user-provided PP-OCRv5 ONNX files
  - `EYEX_OCR_OPENAI_MODEL=` for OpenAI Responses file/vision parsing
- `backend/requirements-ocr-intelligent.txt` lists optional heavy dependencies.
- `config/ocr_profiles/*.yaml` defines profile-driven engine routing. The default
  `windows_radeon_balanced` profile routes ordinary scanned/image pages through
  `pp_ocr_v5_onnx_directml -> pp_ocr_v5_paddle -> paddle_structure_v3 -> docling -> paddleocr_vl`.

The main FastAPI process can stay on Python 3.14. Heavy local OCR stacks should
run in a Python 3.9-3.13 sidecar and expose a `POST /extract` endpoint returning
JSON blocks:

```json
{
  "engine": "paddleocr_vl_sidecar",
  "blocks": [
    {
      "page": 1,
      "text": "姓名：张三",
      "bbox": [10, 20, 100, 40],
      "confidence": 0.94,
      "block_type": "form_field"
    }
  ]
}
```

OpenAI Responses can also accept PDF file inputs with both extracted text and
page images on vision-capable models, so `openai_document_vision` is available
as a high-difficulty fallback when `EYEX_OPENAI_API_KEY` is configured.

## Automated installation

On Windows, use Python 3.11 for the OCR sidecar:

```powershell
.\install-ocr.cmd -PythonExe py -PythonArgs -3.11 -UseDeepSeek -StartSidecar
```

The script:

1. Detects the local GPU and resolves an OCR route before installing packages.
   The default `-GpuPolicy Require` fails fast unless EYEX can validate a GPU
   OCR path. Use `-GpuPolicy Auto` only when CPU fallback is acceptable.
2. Creates `.venv-ocr`.
3. Installs the package set for the selected route: NVIDIA CUDA Paddle,
   Windows DirectML ONNX, remote ROCm sidecar wiring, or CPU fallback.
   The Windows CPU sidecar pins PaddlePaddle `3.2.2` because newer local
   3.3.x CPU wheels triggered PP-StructureV3 oneDNN execution errors in this
   app's test environment.
4. Warms up PP-OCRv5, PaddleOCR-VL, PP-StructureV3, and Docling so the first production
   case does not spend the request timeout downloading model weights. Use
   `-SkipWarmup` only if you want the first request to download lazily.
5. Sets `PADDLE_PDX_MODEL_SOURCE=BOS` and disables the model-source connectivity
   check to avoid HuggingFace download stalls on restricted networks.
6. Writes `.env` values for `document_ai_http`.
7. Optionally sets `EYEX_MODEL_PROFILE=deepseek_v4_flash` when `-UseDeepSeek`
   is passed.
8. Starts the sidecar on `http://127.0.0.1:8765` unless a remote ROCm sidecar
   route is selected.

Run later with:

```powershell
.\start-ocr-sidecar.cmd
```

Then `start.cmd` will also auto-start the sidecar when `.venv-ocr` exists.

### GPU policy

`scripts/install-intelligent-ocr.ps1` resolves one GPU route at install time and
writes the chosen route to `.env` as `EYEX_OCR_GPU_ROUTE`,
`EYEX_OCR_PROFILE`, `EYEX_OCR_ACCELERATOR`, and related model settings.

Supported install-time routes:

- NVIDIA with `nvidia-smi`: `cuda_paddle`, `EYEX_OCR_ACCELERATOR=cuda`, and
  PaddlePaddle CUDA wheels. The installer validates `paddle.set_device('gpu')`.
- AMD Radeon on Windows with PP-OCRv5 ONNX files: `windows_radeon_balanced`,
  `EYEX_OCR_ACCELERATOR=directml`, and ONNX Runtime DirectML. The installer
  automatically prepares RapidOCR PP-OCRv5 mobile detection/recognition ONNX
  models under `var\models\ppocrv5-directml`; no manual model download is
  required. It validates that both ONNX sessions load with
  `DmlExecutionProvider`; otherwise installation stops.
- AMD with a validated ROCm/VL service: `rocm_remote_vl`,
  `EYEX_OCR_ACCELERATOR=remote`. Pass
  `-RemoteRocmSidecarUrl http://host:8765/extract`.
- Explicit CPU fallback: pass `-GpuPolicy Off`, which writes `cpu_stable`.

Legacy `-UseGpu` now means "require the NVIDIA/CUDA Paddle route"; legacy
`-UseDirectML` now means "require the Windows DirectML ONNX route." Both
switches fail if hardware detection selects a different route.

For AMD Radeon cards on Windows, use the default installer command. With
`-GpuPolicy Require`, EYEX automatically selects DirectML, creates the model
directory inside the project, downloads RapidOCR PP-OCRv5 ONNX artifacts, and
validates that detection, classification, and recognition sessions activate
`DmlExecutionProvider`. Missing model files are no longer a manual setup step.
`-DirectMLModelDir` remains available only for a project-local
override; paths outside the EYEX folder are rejected. ROCm/HIP support for
PaddleOCR-VL should be hosted as a separate Linux/ROCm or vendor-provided OCR
service after validating the exact GPU and framework combination.

All OCR model and cache writes are kept under the project directory:

- Models: `var\models\...`
- Install-time caches: `var\cache\ocr-install\...`
- Runtime caches: `var\cache\ocr-runtime\...`

The installer sets `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `PIP_CACHE_DIR`,
`PADDLE_HOME`, `PADDLEOCR_HOME`, `PADDLEX_HOME`, `XDG_CACHE_HOME`, and
`PADDLE_PDX_CACHE_HOME`, and `TORCH_HOME` to project-local paths before
installing or warming up models.

Run the read-only probe with:

```powershell
.\scripts\probe-amd-ocr.ps1
```

For the current RX 6600 class Windows workstation, ROCm is not enabled as the
default PaddleOCR-VL path. Use a remote ROCm sidecar for `PaddleOCR-VL-1.5`, and
use local DirectML only for PP-OCRv5 ONNX when the model directory and provider
are ready.

DeepSeek is intentionally used after OCR, for structured extraction from text
evidence. The official DeepSeek API exposes Chat Completions text messages and
JSON output, so it is not wired as a direct PDF/image OCR engine.

## Open-source candidates

| Project | Best use in EYEX | Notes |
| --- | --- | --- |
| PaddleOCR PP-OCRv5 | First choice for ordinary Chinese/English OCR pages and Windows Radeon DirectML experiments | Official OCR docs support `ocr_version="PP-OCRv5"`; DirectML requires ONNX files and ONNX Runtime DirectML. |
| PaddleOCR PP-StructureV3 | First choice for layout, tables, reading order, and Markdown-like document reconstruction | Official docs describe stronger layout detection, table recognition, formula recognition, chart understanding, and reading-order restoration. |
| PaddleOCR-VL | Best candidate for difficult in-the-wild document parsing when GPU/runtime is available | Official docs describe a compact VLM for text, tables, formulas, and complex real-world layouts; AMD GPU usage should run through validated ROCm sidecar/container. |
| Docling | Good general document conversion layer for RAG/doc ingestion | Strong PDF understanding, table structure, reading order, local execution, and OCR support. |
| Marker | PDF to Markdown/JSON conversion; useful for document normalization experiments | GPL-3.0, so keep license implications isolated if used. |
| docTR | Lightweight deep-learning OCR engine alternative | Good OCR library, but not a full table/form understanding stack by itself. |
| Unstructured | ETL-style document partitioning for LLM workflows | Useful for ingestion pipelines, but not the strongest choice for Chinese medical screenshots. |

Primary links:

- https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-StructureV3/PP-StructureV3.html
- https://www.paddleocr.ai/main/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html
- https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html
- https://www.paddleocr.ai/main/en/version3.x/deployment/obtaining_onnx_models.html
- https://www.paddleocr.ai/main/en/version3.x/algorithm/PaddleOCR-VL/PaddleOCR-VL.html
- https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PaddleOCR-VL-AMD-GPU.html
- https://www.amd.com/en/developer/resources/technical-articles/2026/unlocking-high-performance-document-parsing-of-paddleocr-vl-1-5-.html
- https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html
- https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/wsl/wsl_compatibility.html
- https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html
- https://github.com/docling-project/docling
- https://developers.openai.com/api/docs/guides/file-inputs
- https://github.com/datalab-to/marker
- https://github.com/mindee/doctr
- https://github.com/Unstructured-IO/unstructured

## Integration plan

1. Use the existing adapter interface:
   - input: one image/PDF page or extracted embedded image
   - output: blocks with `text`, `bbox`, `confidence`, `block_type`, `table_id`, `row`, `col`, `source_engine`
2. Start with PaddleOCR-VL as the primary difficult-document parser.
3. Use PP-StructureV3 for table/layout pages.
4. Use Docling for general document conversion.
5. Route by quality:
   - native PDF text: direct text extraction
   - image PDF or image: intelligent document engines only
   - conflicting/low-confidence output: manual review

## Evaluation slices

Use these slices before changing the production default:

- clear native PDF
- clear scan image
- Word image-PDF with embedded images
- multi-screenshot page
- dense medical text
- table/form page
- checkbox/selection mark
- high moire/low contrast page
- truncated content page

Track:

- page OCR character recall on manually transcribed samples
- field extraction accuracy after OCR
- percentage of fields routed to manual review
- p95 OCR latency per page
- false confidence rate: wrong text with high confidence
