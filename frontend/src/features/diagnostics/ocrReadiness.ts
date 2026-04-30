export function ocrReadinessSummary(
  attemptedEngines: string[],
  unavailableEngines: string[],
  unavailableReasons: Record<string, string>
) {
  const reasonLabels = readinessReasonLabels(unavailableReasons);
  const prefix = reasonLabels.length ? `${reasonLabels.join(" / ")} / ` : "";
  return `${prefix}缺失 ${unavailableEngines.length || 0} / 尝试 ${attemptedEngines.length || 0}`;
}

export function formatOcrProcessingError(error: string | null | undefined, unavailableReasons: Record<string, string>) {
  if (!error) return null;
  if (!error.includes("OCR_ENGINE_UNAVAILABLE")) return error;
  const reasonLabels = readinessReasonLabels(unavailableReasons, true);
  if (!reasonLabels.length) return "智能文档引擎未就绪";
  return `智能文档引擎未就绪：${reasonLabels.join("，")}`;
}

function readinessReasonLabels(unavailableReasons: Record<string, string>, detailed = false) {
  const reasons = Object.values(unavailableReasons).join(" \n ");
  const labels: string[] = [];
  if (/OCR_DOCUMENT_AI_URL|OPENAI_API_KEY/.test(reasons)) {
    labels.push(detailed ? "未配置文档服务或模型密钥" : "未配置服务或密钥");
  }
  if (/paddleocr|docling|not installed/i.test(reasons)) {
    labels.push(detailed ? "本地 PaddleOCR/Docling 未安装" : "本地引擎未安装");
  }
  return labels.length ? labels : Object.keys(unavailableReasons).slice(0, 2);
}
