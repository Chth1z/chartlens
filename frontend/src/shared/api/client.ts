import { ApiError } from "./apiError.js";
import { parse } from "./parse.js";
import {
  authStatusSchema,
  modelProviderActivationResponseSchema,
  modelProviderFetchResponseSchema,
  modelProviderUpdateResponseSchema,
  modelProvidersResponseSchema,
  runtimeSettingsResponseSchema,
  systemSettingsResponseSchema
} from "./schemas.js";
import type {
  AuthStatus,
  CaseDiagnostics,
  CaseRecord,
  CaseSummary,
  DocumentIrResponse,
  FieldDictionary,
  FieldDictionarySettingsResponse,
  FieldResult,
  MaintenanceResult,
  ModelProfileSelectionResponse,
  ModelProfilesResponse,
  ModelProviderActivationResponse,
  ModelProviderFetchResponse,
  ModelProviderUpdatePayload,
  ModelProviderUpdateResponse,
  ModelProvidersResponse,
  ProjectConfig,
  RuntimeSettingsResponse,
  SettingsValidationPayload,
  SettingsValidationResponse,
  SourceOcrResponse,
  SystemSettingsResponse,
  VisionFallbackRecord
} from "../types/api";

export { ApiError };

const API_BASE = import.meta.env?.VITE_API_BASE ?? "";

type ResponseValidator<T> = (payload: unknown) => T;

async function request<T>(path: string, init?: RequestInit, validate?: ResponseValidator<T>): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init
  });
  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }
  const payload = await parseResponseBody(response);
  return validate ? validate(payload) : (payload as T);
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  const payload = await parseResponseBody(response);
  if (isRecord(payload) && "detail" in payload) {
    return new ApiError(response.status, detailToMessage(payload.detail), payload.detail);
  }
  return new ApiError(response.status, detailToMessage(payload) || `Request failed: ${response.status}`, payload);
}

function detailToMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(detailToMessage).filter(Boolean).join("; ");
  if (isRecord(detail)) {
    if (typeof detail.msg === "string") return detail.msg;
    if (typeof detail.message === "string") return detail.message;
    return JSON.stringify(detail);
  }
  if (detail == null) return "";
  return String(detail);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// --- Public API ---

export function getAuthStatus(): Promise<AuthStatus> {
  return request<AuthStatus>("/api/auth/me", undefined, (payload) => parse(authStatusSchema, payload, "AuthStatus") as AuthStatus);
}

export function getModelProfiles(): Promise<ModelProfilesResponse> {
  return request<ModelProfilesResponse>("/api/model-profiles");
}

export function updateActiveModelProfile(profileId: string): Promise<ModelProfileSelectionResponse> {
  return request<ModelProfileSelectionResponse>("/api/model-profiles/active", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_id: profileId })
  });
}

export function getModelProviders(): Promise<ModelProvidersResponse> {
  return request<ModelProvidersResponse>(
    "/api/model-providers",
    undefined,
    (payload) => parse(modelProvidersResponseSchema, payload, "ModelProvidersResponse") as ModelProvidersResponse
  );
}

export function updateModelProvider(providerId: string, payload: ModelProviderUpdatePayload): Promise<ModelProviderUpdateResponse> {
  return request<ModelProviderUpdateResponse>(
    `/api/model-providers/${providerId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    },
    (responsePayload) =>
      parse(modelProviderUpdateResponseSchema, responsePayload, "ModelProviderUpdateResponse") as ModelProviderUpdateResponse
  );
}

export function fetchProviderModels(providerId: string): Promise<ModelProviderFetchResponse> {
  return request<ModelProviderFetchResponse>(
    `/api/model-providers/${providerId}/models/fetch`,
    { method: "POST" },
    (payload) => parse(modelProviderFetchResponseSchema, payload, "ModelProviderFetchResponse") as ModelProviderFetchResponse
  );
}

export function activateProviderModel(providerId: string, modelId: string): Promise<ModelProviderActivationResponse> {
  return request<ModelProviderActivationResponse>(
    "/api/model-providers/active",
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider_id: providerId, model_id: modelId })
    },
    (payload) =>
      parse(modelProviderActivationResponseSchema, payload, "ModelProviderActivationResponse") as ModelProviderActivationResponse
  );
}

export function deleteModelToken(): Promise<MaintenanceResult> {
  return request<MaintenanceResult>("/api/auth/model-token", { method: "DELETE" });
}

export function listCases(): Promise<CaseRecord[]> {
  return request<CaseSummary[]>("/api/cases").then((cases) => cases.map(toCaseRecord));
}

export function getCaseDiagnostics(caseId: string): Promise<CaseDiagnostics> {
  return request<CaseDiagnostics>(`/api/cases/${caseId}/diagnostics`);
}

export function reprocessCase(caseId: string): Promise<CaseRecord> {
  return request<CaseSummary>(`/api/cases/${caseId}/reprocess`, { method: "POST" }).then(toCaseRecord);
}

export function deleteCase(caseId: string): Promise<MaintenanceResult> {
  return request<MaintenanceResult>(`/api/cases/${caseId}`, { method: "DELETE" });
}

export function requestVisionFallback(
  caseId: string,
  payload: {
    field_key?: string | null;
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

export function getProjectConfig(): Promise<ProjectConfig> {
  return request<ProjectConfig>("/api/project-config");
}

export function getSystemSettings(): Promise<SystemSettingsResponse> {
  return request<SystemSettingsResponse>("/api/settings/system", undefined, (payload) => {
    parse(systemSettingsResponseSchema, payload, "SystemSettings");
    return payload as SystemSettingsResponse;
  });
}

export function getFieldDictionarySettings(): Promise<FieldDictionarySettingsResponse> {
  return request<FieldDictionarySettingsResponse>("/api/settings/field-dictionary");
}

export function getRuntimeSettings(): Promise<RuntimeSettingsResponse> {
  return request<RuntimeSettingsResponse>("/api/settings/runtime", undefined, (payload) => {
    parse(runtimeSettingsResponseSchema, payload, "RuntimeSettings");
    return payload as RuntimeSettingsResponse;
  });
}

export function validateSettings(payload: SettingsValidationPayload = {}): Promise<SettingsValidationResponse> {
  return request<SettingsValidationResponse>("/api/settings/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function clearProcessingCache(): Promise<MaintenanceResult> {
  return request<MaintenanceResult>("/api/maintenance/clear-cache", { method: "POST" });
}

export function clearAllCases(): Promise<MaintenanceResult> {
  return request<MaintenanceResult>("/api/maintenance/clear-all-cases", { method: "POST" });
}

export async function uploadCase(file: File): Promise<CaseRecord> {
  const formData = new FormData();
  formData.append("file", file);
  return request<CaseSummary>("/api/cases", {
    method: "POST",
    body: formData
  }).then(toCaseRecord);
}

export function getCaseResults(caseId: string): Promise<FieldResult[]> {
  return request<FieldResult[]>(`/api/cases/${caseId}/results`);
}

export function getCaseDocumentIr(caseId: string): Promise<DocumentIrResponse> {
  return request<DocumentIrResponse>(`/api/cases/${caseId}/document-ir`);
}

export function getCaseSourceOcr(caseId: string): Promise<SourceOcrResponse> {
  return request<SourceOcrResponse>(`/api/cases/${caseId}/source-ocr`);
}

export function updateReview(
  caseId: string,
  payload: {
    field_key: string;
    raw_value: string;
    normalized_code: string;
    comment: string;
    reviewer: string;
  }
): Promise<FieldResult> {
  return request<FieldResult>(`/api/cases/${caseId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      field_key: payload.field_key,
      raw_value: payload.raw_value,
      normalized_code: payload.normalized_code,
      reviewer: payload.reviewer,
      comment: payload.comment
    })
  });
}

export function exportUrl(caseId: string): string {
  return `${API_BASE}/api/cases/${encodeURIComponent(caseId)}/export`;
}

export async function downloadCaseExport(caseId: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(exportUrl(caseId), { credentials: "include" });
  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }
  return {
    blob: await response.blob(),
    filename: exportFilename(response.headers.get("Content-Disposition"), caseId)
  };
}

export function sourcePageImageUrl(caseId: string, page: number, retryToken = 0): string {
  const path = `${API_BASE}/api/cases/${encodeURIComponent(caseId)}/source-pages/${page}`;
  return retryToken > 0 ? `${path}?retry=${encodeURIComponent(String(retryToken))}` : path;
}

function exportFilename(contentDisposition: string | null, caseId: string) {
  const match = contentDisposition?.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i);
  if (!match) return `${caseId}.xlsx`;
  try {
    return decodeURIComponent(match[1].replace(/^"|"$/g, ""));
  } catch {
    return match[1].replace(/^"|"$/g, "");
  }
}

function toCaseRecord(summary: CaseSummary): CaseRecord {
  return {
    ...summary,
    error_message: null,
    results: [],
    ocr_blocks: [],
    audit_count: summary.audit_count ?? 0,
    latest_run: null
  };
}
