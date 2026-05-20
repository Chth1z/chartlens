import { AlertTriangle, Archive, CheckCircle2, Loader2, XCircle } from "lucide-react";
import type { AuthStatus, CaseRecord, FieldResult } from "../../shared/types/api";

export type FilterMode = "all" | "model_failed" | "ocr_low" | "no_evidence" | "review" | "manual_review" | "accepted" | "unknown";

export function confidenceBand(result: FieldResult): FilterMode {
  if (result.validation_state === "reviewed" || result.acceptance_reason === "manual_review") return "manual_review";
  if (result.review_required) return "review";
  if (result.normalized_code === "unknown" || result.error_code) return "unknown";
  return "accepted";
}

export function resultMatchesFilter(result: FieldResult, filter: FilterMode) {
  if (filter === "all") return true;
  if (filter === "model_failed") return result.error_code === "LLM_PROVIDER_FAILED" || result.error_code?.startsWith("LLM_PROVIDER_FAILED:");
  if (filter === "ocr_low") return result.error_code === "LOW_OCR_CONFIDENCE" || result.evidence_packs?.some((pack) => pack.ocr_confidence < 0.75);
  if (filter === "no_evidence") return result.error_code === "NO_EVIDENCE_CANDIDATES_SKIPPED_LLM";
  return confidenceBand(result) === filter;
}

export function isWorkingStatus(status: CaseRecord["status"]) {
  return status === "queued" || status === "processing" || status === "ocr" || status === "extracting";
}

export function statusLabel(status: CaseRecord["status"]) {
  if (status === "queued") return "队列中";
  if (status === "processing") return "处理中";
  if (status === "ocr") return "OCR中";
  if (status === "extracting") return "抽取中";
  if (status === "completed") return "已完成";
  if (status === "degraded") return "已降级";
  if (status === "archived") return "已归档";
  return "失败";
}

export function statusIcon(status: CaseRecord["status"]) {
  if (status === "completed") return <CheckCircle2 size={16} />;
  if (status === "degraded") return <AlertTriangle size={16} />;
  if (status === "archived") return <Archive size={16} />;
  if (status === "failed") return <XCircle size={16} />;
  return <Loader2 size={16} className="spin" />;
}

export function qualityText(band: string | undefined) {
  if (band === "good") return "良好";
  if (band === "fair") return "一般";
  if (band === "poor") return "较差";
  return "未知";
}

export { formatMs } from "../../shared/utils/formatters";

export function modelAuthLabel(auth: AuthStatus | null, provider?: string) {
  const activeProvider = provider || auth?.model_auth.provider;
  if (activeProvider?.includes("deepseek")) return "DeepSeek";
  if (activeProvider?.includes("openrouter")) return "OpenRouter";
  if (activeProvider?.includes("ollama")) return "Ollama";
  if (activeProvider?.includes("lmstudio")) return "LM Studio";
  if (activeProvider?.includes("vllm")) return "vLLM";
  if (activeProvider?.includes("local_after_model_fallback") || activeProvider?.includes("conservative-local-provider")) return "本地规则 fallback";
  if (activeProvider === "openai_api_key" || activeProvider === "openai-responses") return "OpenAI API key";
  if (activeProvider === "deepseek" || activeProvider === "deepseek-chat") return "DeepSeek";
  if (activeProvider === "openrouter") return "OpenRouter";
  if (activeProvider === "ollama") return "Ollama";
  if (activeProvider === "lmstudio") return "LM Studio";
  if (activeProvider === "vllm") return "vLLM";
  if (activeProvider === "custom") return "自定义兼容接口";
  if (activeProvider === "openai_compatible" || activeProvider === "openai-compatible-chat") return "OpenAI-compatible";
  if (activeProvider === "chatgpt_codex" || activeProvider === "chatgpt-codex-responses") return "ChatGPT/Codex";
  return "本地规则 fallback";
}
