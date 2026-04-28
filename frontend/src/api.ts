import type { AuthStatus, CaseDiagnostics, CaseRecord, FieldDictionary, FieldResult, VisionFallbackRecord } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getAuthStatus(): Promise<AuthStatus> {
  return request<AuthStatus>("/api/auth/me");
}

export function loginUrl(next = "/"): string {
  return `${API_BASE}/api/auth/login?next=${encodeURIComponent(next)}`;
}

export function logoutUrl(): string {
  return `${API_BASE}/api/auth/logout`;
}

export function completeChatGptLogin(ticket: string): Promise<{ ok: boolean; next: string }> {
  return request<{ ok: boolean; next: string }>(`/api/auth/chatgpt/complete?ticket=${encodeURIComponent(ticket)}`);
}

export function listCases(): Promise<CaseRecord[]> {
  return request<CaseRecord[]>("/api/cases");
}

export function getCaseDiagnostics(caseId: string): Promise<CaseDiagnostics> {
  return request<CaseDiagnostics>(`/api/cases/${caseId}/diagnostics`);
}

export function reprocessCase(caseId: string): Promise<CaseRecord> {
  return request<CaseRecord>(`/api/cases/${caseId}/reprocess`, { method: "POST" });
}

export function requestVisionFallback(
  caseId: string,
  payload: {
    page: number;
    bbox: number[];
    reason: string;
    reviewer: string;
    manual_redaction_confirmed: boolean;
  }
): Promise<VisionFallbackRecord> {
  return request<VisionFallbackRecord>(`/api/cases/${caseId}/vision-fallback-requests`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function getFieldDictionary(): Promise<FieldDictionary> {
  return request<FieldDictionary>("/api/field-dictionary");
}

export async function uploadCase(file: File): Promise<CaseRecord> {
  const formData = new FormData();
  formData.append("file", file);
  return request<CaseRecord>("/api/cases", {
    method: "POST",
    body: formData
  });
}

export function updateReview(
  caseId: string,
  payload: {
    field_key: string;
    new_raw_value: string;
    new_normalized_code: string;
    reason: string;
    reviewer: string;
  }
): Promise<FieldResult> {
  return request<FieldResult>(`/api/cases/${caseId}/review`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function exportUrl(caseId: string): string {
  return `${API_BASE}/api/cases/${caseId}/export.xlsx`;
}
