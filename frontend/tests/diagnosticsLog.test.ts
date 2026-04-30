import { buildDiagnosticsTimeline, formatDuration, formatTokenSummary, summarizeModelCalls } from "../src/features/diagnostics/diagnosticsLog.js";
import type { ModelCallLog, ProcessingRun } from "../src/shared/types/api";

function assertEqual<T>(actual: T, expected: T, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, received ${actual}`);
  }
}

function run(overrides: Partial<ProcessingRun>): ProcessingRun {
  return {
    run_id: "run",
    status: "completed",
    ocr_profile: "intelligent",
    layout_profile: "chinese_inpatient_v1",
    llm_profile: "deepseek_v4_flash",
    parser_mode: "document_ir",
    page_count: 1,
    ocr_block_count: 10,
    fragment_count: 8,
    avg_ocr_confidence: 0.9,
    low_confidence_block_count: 0,
    quality_band: "good",
    auto_accept_count: 2,
    review_required_count: 3,
    unknown_count: 1,
    input_tokens: 100,
    cached_input_tokens: 20,
    output_tokens: 40,
    cost_usd: 0.001,
    latency_ms: 1200,
    step_timings: {},
    error_message: null,
    created_at: "2026-04-29T01:00:00Z",
    completed_at: "2026-04-29T01:00:02Z",
    ...overrides
  };
}

function modelCall(overrides: Partial<ModelCallLog>): ModelCallLog {
  return {
    call_id: "call",
    provider: "deepseek",
    model: "deepseek-v4-flash",
    mode: "extract",
    field_keys: ["age"],
    input_tokens: 100,
    cached_input_tokens: 20,
    output_tokens: 40,
    cost_usd: 0.001,
    latency_ms: 500,
    status: "completed",
    error_code: null,
    created_at: "2026-04-29T01:00:00Z",
    ...overrides
  };
}

const timeline = buildDiagnosticsTimeline(
  [
    run({ run_id: "older", status: "failed", created_at: "2026-04-29T01:00:00Z", error_message: "OCR failed" }),
    run({ run_id: "newer", status: "completed", created_at: "2026-04-29T03:00:00Z", auto_accept_count: 5, review_required_count: 1, unknown_count: 0 })
  ],
  "newer"
);

assertEqual(timeline[0].runId, "newer", "timeline should sort newest run first");
assertEqual(timeline[0].isLatest, true, "latest run should be marked");
assertEqual(timeline[0].fieldSummary, "5 自动 / 1 复核 / 0 不详", "field summary should expose review workload");
assertEqual(timeline[1].tone, "error", "failed runs should use error tone");
assertEqual(formatDuration(0), "未记录", "zero duration should not be shown as a measured latency");
assertEqual(formatTokenSummary(0, 0, 0), "未记录", "empty token values should not be shown as measured usage");

const modelSummary = summarizeModelCalls([
  modelCall({ call_id: "a", status: "completed", input_tokens: 100, cached_input_tokens: 25, output_tokens: 40, cost_usd: 0.001 }),
  modelCall({ call_id: "b", status: "failed", input_tokens: 20, cached_input_tokens: 0, output_tokens: 0, cost_usd: 0.002, error_code: "timeout" })
]);

assertEqual(modelSummary.totalCalls, 2, "summary should count model calls");
assertEqual(modelSummary.failedCalls, 1, "summary should count failed model calls");
assertEqual(modelSummary.totalTokens, 185, "summary should include input, cached input, and output tokens");
assertEqual(modelSummary.hasTokenData, true, "summary should report whether token data was recorded");
assertEqual(modelSummary.costLabel, "$0.0030", "summary should format accumulated cost");
