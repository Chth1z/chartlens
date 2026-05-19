import { describe, it, expect } from "vitest";
import { buildDiagnosticsTimeline, formatDuration, formatTokenSummary, summarizeModelCalls } from "../src/features/diagnostics/diagnosticsLog";
import type { ModelCallLog, ProcessingRun } from "../src/shared/types/api";

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

describe("diagnosticsLog", () => {
  it("timeline should sort newest run first and mark latest", () => {
    const timeline = buildDiagnosticsTimeline(
      [
        run({ run_id: "older", status: "failed", created_at: "2026-04-29T01:00:00Z", error_message: "OCR failed" }),
        run({ run_id: "newer", status: "completed", created_at: "2026-04-29T03:00:00Z", auto_accept_count: 5, review_required_count: 1, unknown_count: 0 })
      ],
      "newer"
    );

    expect(timeline[0].runId).toBe("newer");
    expect(timeline[0].isLatest).toBe(true);
    expect(timeline[0].fieldSummary).toBe("5 自动 / 1 复核 / 0 不详");
    expect(timeline[1].tone).toBe("error");
  });

  it("zero duration should not be shown as a measured latency", () => {
    expect(formatDuration(0)).toBe("未记录");
  });

  it("empty token values should not be shown as measured usage", () => {
    expect(formatTokenSummary(0, 0, 0)).toBe("未记录");
  });

  it("summarizeModelCalls should aggregate call statistics", () => {
    const modelSummary = summarizeModelCalls([
      modelCall({ call_id: "a", status: "completed", input_tokens: 100, cached_input_tokens: 25, output_tokens: 40, cost_usd: 0.001 }),
      modelCall({ call_id: "b", status: "failed", input_tokens: 20, cached_input_tokens: 0, output_tokens: 0, cost_usd: 0.002, error_code: "timeout" })
    ]);

    expect(modelSummary.totalCalls).toBe(2);
    expect(modelSummary.failedCalls).toBe(1);
    expect(modelSummary.totalTokens).toBe(185);
    expect(modelSummary.hasTokenData).toBe(true);
    expect(modelSummary.costLabel).toBe("$0.0030");
  });
});
