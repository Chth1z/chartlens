import { formatOcrProcessingError, ocrReadinessSummary } from "../src/features/diagnostics/ocrReadiness.js";

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
  "未配置服务或密钥 / 本地引擎未安装 / 缺失 3 / 尝试 0",
  "readiness summary should explain why no intelligent engine is ready"
);

assertEqual(
  formatOcrProcessingError("OCR_ENGINE_UNAVAILABLE: intelligent OCR produced no usable result", reasons),
  "智能文档引擎未就绪：未配置文档服务或模型密钥，本地 PaddleOCR/Docling 未安装",
  "OCR engine errors should be localized and actionable"
);
