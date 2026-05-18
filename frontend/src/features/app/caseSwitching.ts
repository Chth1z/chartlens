import type { CaseDiagnostics, CaseRecord } from "../../shared/types/api";

export function diagnosticsForCase(diagnostics: CaseDiagnostics | null, caseId?: string): CaseDiagnostics | null {
  if (!diagnostics || !caseId) return null;
  return diagnostics.case_id === caseId ? diagnostics : null;
}

export function caseHasDetailPayload(caseRecord?: CaseRecord | null): boolean {
  if (!caseRecord) return false;
  return caseRecord.results.length > 0 || caseRecord.ocr_blocks.length > 0;
}

export function caseNeedsDetailHydration(caseRecord: CaseRecord): boolean {
  if (caseHasDetailPayload(caseRecord)) return false;
  return caseRecord.result_count > 0 || caseRecord.review_required_count > 0;
}

export function mergeCaseRecord(next: CaseRecord, existing?: CaseRecord): CaseRecord {
  if (!existing) return next;
  return {
    ...next,
    results: existing.results,
    ocr_blocks: existing.ocr_blocks,
    audit_count: existing.audit_count,
    latest_run: existing.latest_run,
    quality: existing.quality,
    error_message: existing.error_message
  };
}
