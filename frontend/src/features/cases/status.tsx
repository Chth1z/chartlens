import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import type { AuthStatus, CaseRecord, FieldResult } from "../../shared/types/api";

export type FilterMode = "all" | "review" | "unknown" | "accepted";

export function confidenceBand(result: FieldResult): FilterMode {
  if (result.review_required) return "review";
  if (result.normalized_code === "unknown" || result.error_code) return "unknown";
  return "accepted";
}

export function isWorkingStatus(status: CaseRecord["status"]) {
  return status === "queued" || status === "processing" || status === "ocr" || status === "extracting";
}

export function statusLabel(status: CaseRecord["status"]) {
  if (status === "queued") return "队列中";
  if (status === "processing") return "处理中";
  if (status === "ocr") return "OCR中";
  if (status === "extracting") return "抽取中";
  if (status === "processed") return "已完成";
  if (status === "degraded") return "已降级";
  return "失败";
}

export function statusIcon(status: CaseRecord["status"]) {
  if (status === "processed") return <CheckCircle2 size={16} />;
  if (status === "degraded") return <AlertTriangle size={16} />;
  if (status === "failed") return <XCircle size={16} />;
  return <Loader2 size={16} className="spin" />;
}

export function qualityText(band: string | undefined) {
  if (band === "good") return "良好";
  if (band === "fair") return "一般";
  if (band === "poor") return "较差";
  return "未知";
}

export function formatMs(value: number | undefined) {
  if (!value) return "0 ms";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

export function modelAuthLabel(auth: AuthStatus | null, provider?: string) {
  const activeProvider = provider || auth?.model_auth.provider;
  if (activeProvider === "openai_api_key" || activeProvider === "openai-responses") return "OpenAI API key";
  if (activeProvider === "chatgpt_codex" || activeProvider === "chatgpt-codex-responses") return "ChatGPT/Codex";
  return "本地规则 fallback";
}
