import { describe, it, expect } from "vitest";
import { caseHasDetailPayload, caseNeedsDetailHydration, diagnosticsForCase } from "../src/features/app/caseSwitching";
import type { CaseDiagnostics, CaseRecord } from "../src/shared/types/api";

function caseRecord(overrides: Partial<CaseRecord>): CaseRecord {
  return {
    case_id: "CASE-A",
    filename: "case.pdf",
    status: "completed",
    error_message: null,
    created_at: "2026-05-01T00:00:00Z",
    updated_at: "2026-05-01T00:00:00Z",
    result_count: 20,
    review_required_count: 4,
    results: [],
    ocr_blocks: [],
    audit_count: 0,
    latest_run: null,
    ...overrides
  };
}

function diagnostics(caseId: string): CaseDiagnostics {
  return {
    case_id: caseId,
    quality: {
      page_count: 1,
      ocr_block_count: 1,
      fragment_count: 1,
      avg_ocr_confidence: 0.9,
      low_confidence_block_count: 0,
      quality_band: "good",
      needs_vision_fallback: false
    },
    latest_run: null,
    run_count: 1,
    runs: [],
    fragments: [
      {
        page: 1,
        reading_order: 1,
        text: "上一病例的证据",
        bbox: [],
        confidence: 0.9,
        section_name: "现病史",
        block_type: "line",
        source_kind: "intelligent_document"
      }
    ],
    model_calls: [],
    vision_requests: [],
    config: {
      ocr_default_profile: "ocr",
      layout_default_profile: "layout",
      llm_default_profile: "llm",
      vision_fallback_enabled: false,
      vision_fallback_requires_manual_approval: true,
      gold_sample_target_min: 0
    }
  };
}

describe("caseSwitching", () => {
  it("completed case summaries without hydrated results or OCR blocks should not drive review panels", () => {
    expect(caseHasDetailPayload(caseRecord({ results: [], ocr_blocks: [], result_count: 20 }))).toBe(false);
  });

  it("case summaries with result counts should show a stable detail loading state while hydrating", () => {
    expect(caseNeedsDetailHydration(caseRecord({ results: [], ocr_blocks: [], result_count: 20 }))).toBe(true);
  });

  it("empty completed cases should not be trapped behind a permanent detail loading overlay", () => {
    expect(caseNeedsDetailHydration(caseRecord({ results: [], ocr_blocks: [], result_count: 0, review_required_count: 0 }))).toBe(false);
  });

  it("cases with hydrated results should drive review panels", () => {
    expect(caseHasDetailPayload(caseRecord({ results: [{ field_key: "gender" } as any] }))).toBe(true);
  });

  it("cases with hydrated OCR blocks should drive review panels", () => {
    expect(caseHasDetailPayload(caseRecord({ ocr_blocks: [{ page: 1, text: "证据", bbox: [], confidence: 0.9 }] as any }))).toBe(true);
  });

  it("diagnostics from the previous case must not be reused after switching cases", () => {
    expect(diagnosticsForCase(diagnostics("CASE-A"), "CASE-B")).toBeNull();
  });

  it("diagnostics matching the selected case should be used", () => {
    expect(diagnosticsForCase(diagnostics("CASE-A"), "CASE-A")?.case_id).toBe("CASE-A");
  });
});
