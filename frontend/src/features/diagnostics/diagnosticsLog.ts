import type { ModelCallLog, ProcessingRun } from "../../shared/types/api";
import { formatDuration, formatTimestamp } from "../../shared/utils/formatters";

export { formatDuration, formatTimestamp };

type DiagnosticsTimelineRow = {
  runId: string;
  shortRunId: string;
  status: string;
  tone: "ok" | "warning" | "error";
  isLatest: boolean;
  createdLabel: string;
  completedLabel: string;
  profileLabel: string;
  fieldSummary: string;
  documentSummary: string;
  tokenSummary: string;
  latencyLabel: string;
  errorMessage: string | null;
};

type ModelCallSummary = {
  totalCalls: number;
  failedCalls: number;
  totalTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  latencyMs: number;
  hasTokenData: boolean;
  hasLatencyData: boolean;
  hasCostData: boolean;
  costLabel: string;
};

export function buildDiagnosticsTimeline(runs: ProcessingRun[], latestRunId?: string | null): DiagnosticsTimelineRow[] {
  return [...runs]
    .sort((left, right) => timestamp(right.created_at) - timestamp(left.created_at))
    .map((run) => ({
      runId: run.run_id,
      shortRunId: compactId(run.run_id),
      status: run.status,
      tone: runTone(run.status, run.error_message),
      isLatest: Boolean(latestRunId && run.run_id === latestRunId),
      createdLabel: formatTimestamp(run.created_at),
      completedLabel: run.completed_at ? formatTimestamp(run.completed_at) : "未完成",
      profileLabel: `${run.ocr_profile} / ${run.layout_profile} / ${run.llm_profile}`,
      fieldSummary: `${run.auto_accept_count} 自动 / ${run.review_required_count} 复核 / ${run.unknown_count} 不详`,
      documentSummary: `${run.page_count} 页 / ${run.ocr_block_count} 块 / ${run.fragment_count} 段`,
      tokenSummary: formatTokenSummary(run.input_tokens, run.cached_input_tokens, run.output_tokens),
      latencyLabel: formatDuration(run.latency_ms),
      errorMessage: run.error_message
    }));
}

export function summarizeModelCalls(calls: ModelCallLog[]): ModelCallSummary {
  const totalCost = calls.reduce((sum, call) => sum + call.cost_usd, 0);
  const totalTokens = calls.reduce((sum, call) => sum + call.input_tokens + call.cached_input_tokens + call.output_tokens, 0);
  const latencyMs = calls.reduce((sum, call) => sum + call.latency_ms, 0);
  return {
    totalCalls: calls.length,
    failedCalls: calls.filter((call) => call.status !== "completed" || call.error_code).length,
    totalTokens,
    cachedInputTokens: calls.reduce((sum, call) => sum + call.cached_input_tokens, 0),
    outputTokens: calls.reduce((sum, call) => sum + call.output_tokens, 0),
    latencyMs,
    hasTokenData: totalTokens > 0,
    hasLatencyData: latencyMs > 0,
    hasCostData: totalCost > 0,
    costLabel: totalCost > 0 ? `$${totalCost.toFixed(4)}` : "费用未记录"
  };
}

export function formatTokenSummary(inputTokens: number | undefined, cachedInputTokens: number | undefined, outputTokens: number | undefined) {
  const input = inputTokens ?? 0;
  const cached = cachedInputTokens ?? 0;
  const output = outputTokens ?? 0;
  if (input + cached + output <= 0) return "未记录";
  return `${input}:${cached}:${output}`;
}

function compactId(value: string) {
  if (value.length <= 12) return value;
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

function runTone(status: string, errorMessage: string | null): DiagnosticsTimelineRow["tone"] {
  if (status === "failed" || errorMessage) return "error";
  if (status === "degraded") return "warning";
  return "ok";
}

function timestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
}
