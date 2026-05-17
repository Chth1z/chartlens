import { caseHasDetailPayload, caseNeedsDetailHydration, diagnosticsForCase } from "../src/features/app/caseSwitching.js";
import type { CaseDiagnostics, CaseRecord } from "../src/shared/types/api";

function assertEqual<T>(actual: T, expected: T, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, received ${actual}`);
  }
}

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

assertEqual(
  caseHasDetailPayload(caseRecord({ results: [], ocr_blocks: [], result_count: 20 })),
  false,
  "completed case summaries without hydrated results or OCR blocks should not drive review panels"
);

assertEqual(
  caseNeedsDetailHydration(caseRecord({ results: [], ocr_blocks: [], result_count: 20 })),
  true,
  "case summaries with result counts should show a stable detail loading state while hydrating"
);

assertEqual(
  caseNeedsDetailHydration(caseRecord({ results: [], ocr_blocks: [], result_count: 0, review_required_count: 0 })),
  false,
  "empty completed cases should not be trapped behind a permanent detail loading overlay"
);

assertEqual(
  caseHasDetailPayload(caseRecord({ results: [{ field_key: "gender" } as any] })),
  true,
  "cases with hydrated results should drive review panels"
);

assertEqual(
  caseHasDetailPayload(caseRecord({ ocr_blocks: [{ page: 1, text: "证据", bbox: [], confidence: 0.9 }] as any })),
  true,
  "cases with hydrated OCR blocks should drive review panels"
);

assertEqual(
  diagnosticsForCase(diagnostics("CASE-A"), "CASE-B"),
  null,
  "diagnostics from the previous case must not be reused after switching cases"
);

assertEqual(
  diagnosticsForCase(diagnostics("CASE-A"), "CASE-A")?.case_id,
  "CASE-A",
  "diagnostics matching the selected case should be used"
);
