import { describe, it, expect } from "vitest";
import {
  formatOcrProcessingError,
  ocrReadinessSummary,
  ocrRuntimeSummary,
  ocrRuntimeTone
} from "../src/features/diagnostics/ocrReadiness";

describe("diagnosticsOcrReadiness", () => {
  const reasons = {
    document_ai_http: "EYEX_OCR_DOCUMENT_AI_URL is not configured",
    openai_document_vision: "EYEX_OPENAI_API_KEY or OPENAI_API_KEY is not configured",
    paddleocr_vl: "Python package 'paddleocr' is not installed in the backend runtime"
  };

  it("readiness summary should explain why no intelligent engine is ready", () => {
    expect(
      ocrReadinessSummary([], ["document_ai_http", "openai_document_vision", "paddleocr_vl"], reasons)
    ).toBe("未配置服务或密钥 / 本地 OCR 未就绪 / 缺失 3 / 尝试 0");
  });

  it("OCR engine errors should be localized and actionable", () => {
    expect(
      formatOcrProcessingError("OCR_ENGINE_UNAVAILABLE: intelligent OCR produced no usable result", reasons)
    ).toBe("智能文档引擎未就绪：未配置文档服务或模型密钥，本地 hybrid OCR 依赖或模型未就绪");
  });

  it("readiness summary should show timeout-based execution failures", () => {
    expect(
      ocrReadinessSummary(["paddleocr_hybrid"], [], {}, { paddleocr_hybrid: "[PAGE_TIMEOUT] paddleocr_hybrid: engine exceeded timeout of 45s" })
    ).toBe("OCR 处理超时 / 缺失 0 / 尝试 1");
  });

  it("processing errors should prioritize timeout failures when no dependency is missing", () => {
    expect(
      formatOcrProcessingError(
        "OCR_ENGINE_UNAVAILABLE: intelligent OCR produced no usable result",
        {},
        { paddleocr_hybrid: "[PAGE_TIMEOUT] paddleocr_hybrid: engine exceeded timeout of 45s" }
      )
    ).toBe("智能文档引擎执行失败：OCR 处理超时，请先检查页渲染、模型预热或异常大页");
  });

  it("processing errors should ask for sidecar restart when contract check fails", () => {
    expect(
      formatOcrProcessingError(
        "OCR_ENGINE_UNAVAILABLE: intelligent OCR produced no usable result",
        {},
        { sidecar_contract: "OCR sidecar is stale or incompatible; restart it with .\\start.cmd" }
      )
    ).toBe("智能文档引擎执行失败：OCR sidecar 代码已过期，请运行 .\\start.cmd 重启");
  });

  it("runtime OCR summary should explain stale disabled VL configuration", () => {
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

    expect(ocrRuntimeSummary(missingVlRuntime)).toBe(
      "OCR 强链路未就绪：旧 PaddleOCR-VL/ROCm 配置残留，请重新安装并重启本地 OCR"
    );
  });

  it("runtime OCR summary should ask for sidecar restart when contract check fails", () => {
    const missingVlRuntime = {
      key: "ocr",
      label: "智能文档 OCR",
      ready: false,
      status: "not_ready",
      summary: "OCR 强准确链路未就绪：已停用的 PaddleOCR-VL 阶段",
      checks: [
        {
          key: "sidecar_api_contract",
          label: "OCR sidecar API contract",
          ready: false,
          status: "restart_required",
          reason: "OCR sidecar is stale or incompatible: expected eyex-ocr-sidecar-v2, got missing. Restart OCR sidecar with .\\start.cmd."
        }
      ]
    };

    expect(ocrRuntimeSummary(missingVlRuntime)).toBe(
      "OCR 强链路未就绪：OCR sidecar 代码已过期，请运行 .\\start.cmd 重启"
    );
  });

  it("runtime OCR sidecar down should be a danger state", () => {
    const missingVlRuntime = {
      key: "ocr",
      label: "智能文档 OCR",
      ready: false,
      status: "not_running",
      summary: "OCR sidecar 未运行",
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

    expect(ocrRuntimeTone(missingVlRuntime)).toBe("danger");
  });
});
