import type { RuntimeServiceStatus } from "../../shared/types/api";

export function ocrReadinessSummary(
  attemptedEngines: string[],
  unavailableEngines: string[],
  unavailableReasons: Record<string, string>,
  engineErrors: Record<string, string> = {},
  traceError = ""
) {
  const reasonLabels = readinessReasonLabels(unavailableReasons);
  const errorLabels = readinessErrorLabels(engineErrors, traceError);
  const prefixLabels = reasonLabels.length ? [...reasonLabels, ...errorLabels] : errorLabels;
  const prefix = prefixLabels.length ? `${dedupeLabels(prefixLabels).join(" / ")} / ` : "";
  return `${prefix}缺失 ${unavailableEngines.length || 0} / 尝试 ${attemptedEngines.length || 0}`;
}

export function formatOcrProcessingError(
  error: string | null | undefined,
  unavailableReasons: Record<string, string>,
  engineErrors: Record<string, string> = {},
  traceError = ""
) {
  const raw = error || traceError || Object.values(engineErrors)[0];
  if (!raw) return null;
  const reasonLabels = readinessReasonLabels(unavailableReasons, true);
  const errorLabels = readinessErrorLabels(engineErrors, traceError, true);
  const fallbackErrorLabels = !reasonLabels.length && !errorLabels.length ? readinessErrorLabels({}, raw, true) : [];
  if (!error?.includes("OCR_ENGINE_UNAVAILABLE") && !reasonLabels.length && !errorLabels.length && !fallbackErrorLabels.length) return raw;
  const labels = dedupeLabels([...reasonLabels, ...errorLabels, ...fallbackErrorLabels]);
  if (!labels.length) {
    return error?.includes("OCR_ENGINE_UNAVAILABLE") ? "智能文档引擎执行失败" : raw;
  }
  const prefix = reasonLabels.length && !errorLabels.length ? "智能文档引擎未就绪" : "智能文档引擎执行失败";
  return `${prefix}：${labels.join("，")}`;
}

export function ocrRuntimeSummary(service: RuntimeServiceStatus | null | undefined) {
  if (!service) return "运行状态读取中";
  if (service.ready === true || service.status === "ready") return service.summary || "OCR 强准确链路已就绪";
  if (service.status === "not_running") return service.summary || "OCR sidecar 未运行";
  if (service.status === "not_configured") return service.summary || "OCR sidecar 未配置";
  const failedChecks = (service.checks ?? []).filter((check) => !check.ready);
  if (failedChecks.length) {
    const labels = failedChecks.map((check) => readinessReasonLabel(check.reason || check.label, true));
    return `OCR 强链路未就绪：${dedupeLabels(labels).join("，")}`;
  }
  return service.summary || "OCR 强链路未就绪";
}

export function ocrRuntimeTone(service: RuntimeServiceStatus | null | undefined): "ok" | "warning" | "danger" {
  if (!service) return "warning";
  if (service.ready === true || service.status === "ready") return "ok";
  if (service.status === "not_running" || service.status === "not_configured") return "danger";
  return "warning";
}

function readinessReasonLabels(unavailableReasons: Record<string, string>, detailed = false) {
  const reasons = Object.values(unavailableReasons).join(" \n ");
  const labels: string[] = [];
  if (/OCR_DOCUMENT_AI_URL|OPENAI_API_KEY/.test(reasons)) {
    labels.push(detailed ? "未配置文档服务或模型密钥" : "未配置服务或密钥");
  }
  for (const reason of Object.values(unavailableReasons)) {
    labels.push(readinessReasonLabel(reason, detailed));
  }
  return labels.length ? dedupeLabels(labels) : Object.keys(unavailableReasons).slice(0, 2);
}

function readinessErrorLabels(engineErrors: Record<string, string>, fallback: string, detailed = false) {
  const sources = Object.values(engineErrors);
  const labels = sources.length
    ? sources.map((reason) => readinessErrorLabel(reason, detailed))
    : fallback
      ? [readinessErrorLabel(fallback, detailed)]
      : [];
  return dedupeLabels(labels);
}

function readinessReasonLabel(reason: string, detailed = false) {
  if (/stale or incompatible|sidecar_api_contract|sidecar_contract|pre-fix NumPy|restart.*sidecar/i.test(reason)) {
    return detailed ? "OCR sidecar 代码已过期，请运行 .\\start.cmd 重启" : "OCR sidecar 需重启";
  }
  if (/OCR_DOCUMENT_AI_URL|OPENAI_API_KEY/.test(reason)) {
    return detailed ? "未配置文档服务或模型密钥" : "未配置服务或密钥";
  }
  if (/EYEX_OCR_PADDLEOCR_VL_URL|PaddleOCR-VL|remote AMD|ROCm/i.test(reason)) {
    return detailed ? "旧 PaddleOCR-VL/ROCm 配置残留，请重新安装并重启本地 OCR" : "旧 VL 配置残留";
  }
  if (/PP-StructureV3|pp_structure|paddle_structure|structure/i.test(reason)) {
    return detailed ? "PP-StructureV3 表格/版面依赖未就绪" : "Structure 未就绪";
  }
  if (/DirectML|DmlExecutionProvider|onnx runtime|onnxruntime|PP-OCRv5|pp_ocr|rapidocr|dml/i.test(reason)) {
    return detailed ? "PP-OCRv5 DirectML 依赖或模型未就绪" : "DirectML OCR 未就绪";
  }
  if (/paddleocr|ppstructure|pp-ocr|not installed|missing required/i.test(reason)) {
    return detailed ? "本地 hybrid OCR 依赖或模型未就绪" : "本地 OCR 未就绪";
  }
  if (/download|warmup|timeout|timed out|read timeout/i.test(reason)) {
    return detailed ? "OCR 模型下载或预热仍在进行" : "模型预热中";
  }
  if (/connection refused|failed to establish|connect|ECONNREFUSED|sidecar/i.test(reason)) {
    return detailed ? "OCR sidecar 未运行或无法连接" : "OCR sidecar 未运行";
  }
  return reason || "未知 OCR 依赖未就绪";
}

function readinessErrorLabel(reason: string, detailed = false) {
  if (/stale or incompatible|sidecar_api_contract|sidecar_contract|pre-fix NumPy|restart.*sidecar/i.test(reason)) {
    return detailed ? "OCR sidecar 代码已过期，请运行 .\\start.cmd 重启" : "OCR sidecar 需重启";
  }
  if (/PAGE_TIMEOUT|timed out|exceeded timeout|stage exceeded timeout/i.test(reason)) {
    return detailed ? "OCR 处理超时，请先检查页渲染、模型预热或异常大页" : "OCR 处理超时";
  }
  if (/DXGI_ERROR|device_removed|DirectML permanently disabled|DmlExecutionProvider|onnxruntime|DirectML/i.test(reason)) {
    return detailed ? "PP-OCRv5 DirectML 运行失败或模型未就绪" : "DirectML 运行失败";
  }
  if (/connection refused|failed to establish|connect|ECONNREFUSED|sidecar/i.test(reason)) {
    return detailed ? "OCR sidecar 未运行或调用失败" : "OCR sidecar 调用失败";
  }
  if (/no stage results|engine returned no blocks|no usable result|no_engine_result/i.test(reason)) {
    return detailed ? "OCR 未产出可用文本或版面结果" : "OCR 无有效结果";
  }
  if (/not configured|not installed|missing required/i.test(reason)) {
    return readinessReasonLabel(reason, detailed);
  }
  return detailed ? reason || "OCR 执行失败" : reason ? "OCR 执行失败" : "";
}

function dedupeLabels(labels: string[]) {
  return [...new Set(labels.filter(Boolean))];
}
