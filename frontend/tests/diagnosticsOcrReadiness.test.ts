import {
  formatOcrProcessingError,
  ocrReadinessSummary,
  ocrRuntimeSummary,
  ocrRuntimeTone
} from "../src/features/diagnostics/ocrReadiness.js";

function assertEqual(actual: string | null, expected: string, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, received ${actual}`);
  }
}

const reasons = {
  document_ai_http: "EYEX_OCR_DOCUMENT_AI_URL is not configured",
  openai_document_vision: "EYEX_OPENAI_API_KEY or OPENAI_API_KEY is not configured",
  paddleocr_vl: "Python package 'paddleocr' is not installed in the backend runtime"
};

assertEqual(
  ocrReadinessSummary([], ["document_ai_http", "openai_document_vision", "paddleocr_vl"], reasons),
  "未配置服务或密钥 / 本地 OCR 未就绪 / 缺失 3 / 尝试 0",
  "readiness summary should explain why no intelligent engine is ready"
);

assertEqual(
  formatOcrProcessingError("OCR_ENGINE_UNAVAILABLE: intelligent OCR produced no usable result", reasons),
  "智能文档引擎未就绪：未配置文档服务或模型密钥，本地 hybrid OCR 依赖或模型未就绪",
  "OCR engine errors should be localized and actionable"
);

assertEqual(
  ocrReadinessSummary(["paddleocr_hybrid"], [], {}, { paddleocr_hybrid: "[PAGE_TIMEOUT] paddleocr_hybrid: engine exceeded timeout of 45s" }),
  "OCR 处理超时 / 缺失 0 / 尝试 1",
  "readiness summary should show timeout-based execution failures"
);

assertEqual(
  formatOcrProcessingError(
    "OCR_ENGINE_UNAVAILABLE: intelligent OCR produced no usable result",
    {},
    { paddleocr_hybrid: "[PAGE_TIMEOUT] paddleocr_hybrid: engine exceeded timeout of 45s" }
  ),
  "智能文档引擎执行失败：OCR 处理超时，请先检查页渲染、模型预热或异常大页",
  "processing errors should prioritize timeout failures when no dependency is missing"
);

assertEqual(
  formatOcrProcessingError(
    "OCR_ENGINE_UNAVAILABLE: intelligent OCR produced no usable result",
    {},
    { sidecar_contract: "OCR sidecar is stale or incompatible; restart it with .\\start.cmd" }
  ),
  "智能文档引擎执行失败：OCR sidecar 代码已过期，请运行 .\\start.cmd 重启",
  "processing errors should ask for sidecar restart when contract check fails"
);

const missingVlRuntime = {
  key: "ocr",
  label: "智能文档 OCR",
  ready: false,
  status: "not_ready",
  summary: "OCR 强准确链路未就绪：已停用的 PaddleOCR-VL 阶段",
  checks: [
    {
      key: "paddleocr_vl",
      label: "已停用的 PaddleOCR-VL 阶段",
      ready: false,
      status: "not_ready",
      reason: "EYEX_OCR_PADDLEOCR_VL_URL is not configured for remote AMD/ROCm PaddleOCR-VL sidecar"
    }
  ]
};

assertEqual(
  ocrRuntimeSummary(missingVlRuntime),
  "OCR 强链路未就绪：旧 PaddleOCR-VL/ROCm 配置残留，请重新安装并重启本地 OCR",
  "runtime OCR summary should explain stale disabled VL configuration"
);

assertEqual(
  ocrRuntimeSummary({
    ...missingVlRuntime,
    checks: [
      {
        key: "sidecar_api_contract",
        label: "OCR sidecar API contract",
        ready: false,
        status: "restart_required",
        reason: "OCR sidecar is stale or incompatible: expected eyex-ocr-sidecar-v2, got missing. Restart OCR sidecar with .\\start.cmd."
      }
    ]
  }),
  "OCR 强链路未就绪：OCR sidecar 代码已过期，请运行 .\\start.cmd 重启",
  "runtime OCR summary should ask for sidecar restart when contract check fails"
);

assertEqual(
  ocrRuntimeTone({ ...missingVlRuntime, status: "not_running", summary: "OCR sidecar 未运行" }),
  "danger",
  "runtime OCR sidecar down should be a danger state"
);
