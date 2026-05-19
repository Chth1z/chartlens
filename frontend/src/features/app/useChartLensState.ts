import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys, useAuthQuery, useCaseDiagnosticsQuery, useCasesQuery, useProjectConfigQuery, useRuntimeQuery } from "../../shared/api/queries";
import type { CaseRecord, DocumentFragment, FieldDefinition } from "../../shared/types/api";
import { isWorkingStatus, modelAuthLabel, resultMatchesFilter, statusLabel, type FilterMode } from "../cases/status";
import { ocrRuntimeTone } from "../diagnostics/ocrReadiness";
import { caseNeedsDetailHydration, diagnosticsForCase } from "./caseSwitching.js";
import { useChartLensActions } from "./useChartLensActions";

export type ActiveView = "review" | "diagnostics" | "settings";

export type ChartLensState = ReturnType<typeof useChartLensState>;

export function useChartLensState() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const routeCaseId = useMemo(() => {
    const match = location.pathname.match(/^\/cases\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }, [location.pathname]);
  const activeView: ActiveView = location.pathname.startsWith("/settings")
    ? "settings"
    : location.pathname.startsWith("/diagnostics")
      ? "diagnostics"
      : "review";

  // --- Server state via TanStack Query ---
  const authQuery = useAuthQuery();
  const auth = authQuery.data ?? null;
  const startupError = authQuery.error?.message ?? null;

  const casesEnabled = !auth?.enabled || auth.authenticated;
  const casesQuery = useCasesQuery(casesEnabled);
  const cases = casesQuery.data ?? [];

  const configQuery = useProjectConfigQuery(casesEnabled);
  const projectConfig = configQuery.data ?? null;
  const fields: FieldDefinition[] = projectConfig?.extraction_schema.fields ?? [];
  const fieldDictionaryError = configQuery.error?.message ?? null;

  const runtimeQuery = useRuntimeQuery(casesEnabled);
  const runtime = runtimeQuery.data ?? null;

  // --- Local UI state ---
  const [selectedId, setSelectedId] = useState(routeCaseId);
  const [filter, setFilter] = useState<FilterMode>("all");
  const [query, setQuery] = useState("");
  const [selectedField, setSelectedField] = useState<string>("");
  const [reviewCode, setReviewCode] = useState("1");
  const [reviewReason, setReviewReason] = useState("人工复核确认");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // --- Diagnostics ---
  const diagnosticsEnabled = ["review", "diagnostics"].includes(activeView) && Boolean(selectedId) && casesEnabled;
  const diagnosticsQuery = useCaseDiagnosticsQuery(selectedId || undefined, diagnosticsEnabled);
  const diagnostics = diagnosticsQuery.data?.payload ?? null;
  const diagnosticsLoading = diagnosticsQuery.isFetching && !diagnosticsQuery.data;

  // Merge diagnostics into cases cache
  useEffect(() => {
    if (!diagnosticsQuery.data || !selectedId) return;
    const { results, ocrBlocks, payload } = diagnosticsQuery.data;
    queryClient.setQueryData<CaseRecord[]>(queryKeys.cases, (old) =>
      (old ?? []).map((record) =>
        record.case_id === selectedId
          ? { ...record, results, ocr_blocks: ocrBlocks as CaseRecord["ocr_blocks"], result_count: results.length, review_required_count: results.filter((r) => r.review_required).length, quality: payload.quality, latest_run: payload.latest_run, error_message: payload.latest_run?.error_message ?? null }
          : record
      )
    );
  }, [diagnosticsQuery.data, selectedId, queryClient]);

  // --- Polling ---
  const hasActiveJobs = useMemo(() => cases.some((record) => isWorkingStatus(record.status)), [cases]);
  useEffect(() => {
    if (!casesEnabled || !hasActiveJobs) return;
    const timer = window.setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cases });
      if (selectedId) void queryClient.invalidateQueries({ queryKey: queryKeys.caseDiagnostics(selectedId) });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [casesEnabled, hasActiveJobs, selectedId, queryClient]);

  // --- Route sync ---
  useEffect(() => { if (routeCaseId && routeCaseId !== selectedId) setSelectedId(routeCaseId); }, [routeCaseId, selectedId]);
  useEffect(() => { if (!selectedId && cases.length > 0) setSelectedId(cases[0].case_id); }, [cases, selectedId]);

  // --- Derived state ---
  const selectedCase = useMemo(() => cases.find((item) => item.case_id === selectedId) ?? cases[0], [cases, selectedId]);
  const fieldMap = useMemo(() => new Map(fields.map((field) => [field.key, field])), [fields]);
  const authIdentity = auth?.session_auth.user?.email ?? auth?.user?.email ?? auth?.session_auth.user?.name ?? auth?.user?.name ?? "已登录用户";
  const sessionAccessLabel = auth?.enabled ? "应用会话" : "本机访问";
  const sessionStateLabel = auth?.enabled ? authIdentity : "无需 OAuth 登录";
  const modelCredentialLabel = auth?.model_auth.online_model_available ? `${modelAuthLabel(auth)} / API Key 已配置` : `${modelAuthLabel(auth)} / 本地回退或未配置凭据`;
  const oauthConfigured = auth?.configured ?? true;
  const missingOauthConfig = auth?.missing_config ?? [];
  const oauthWarnings = auth?.config_warnings ?? [];
  const deferredQuery = useDeferredValue(query);
  const normalizedQuery = useMemo(() => deferredQuery.trim().toLowerCase(), [deferredQuery]);
  const filteredResults = useMemo(() => {
    if (!selectedCase) return [];
    return selectedCase.results.filter((result) => {
      const field = fieldMap.get(result.field_key);
      const text = `${field?.label ?? result.field_key} ${result.raw_value ?? ""} ${result.evidence_text ?? ""}`;
      return (!normalizedQuery || text.toLowerCase().includes(normalizedQuery)) && resultMatchesFilter(result, filter);
    });
  }, [selectedCase, fieldMap, normalizedQuery, filter]);
  const activeResult = useMemo(() => selectedCase?.results.find((item) => item.field_key === selectedField) ?? filteredResults[0], [filteredResults, selectedCase?.results, selectedField]);
  const activeDiagnostics = diagnosticsForCase(diagnostics, selectedCase?.case_id);
  const activeQuality = activeDiagnostics?.quality ?? selectedCase?.quality;
  const activeRun = activeDiagnostics?.latest_run ?? selectedCase?.latest_run ?? null;
  const cacheHit = Number(activeRun?.step_timings?.cache_hit ?? 0) > 0;
  const cachedInputTokens = activeRun?.cached_input_tokens ?? activeDiagnostics?.model_calls[0]?.cached_input_tokens ?? 0;
  const latestModelProvider = activeDiagnostics?.model_calls[0]?.provider;
  const latestModelLabel = modelAuthLabel(auth, latestModelProvider);
  const latestModelName = activeDiagnostics?.model_calls[0]?.model ?? activeRun?.llm_profile ?? "未记录";
  const modelRuntimeState = auth?.model_auth.online_model_available ? "API Key 已配置" : "本地回退或未配置凭据";
  const sidebarModelUsage = activeRun ? `调用 ${activeDiagnostics?.model_calls.length ?? 0} / tokens ${activeRun.input_tokens}:${cachedInputTokens}:${activeRun.output_tokens}` : "等待处理记录";
  const currentStatusLabel = selectedCase ? statusLabel(selectedCase.status) : "未选择";
  const terms = projectConfig?.app_profile.terms ?? {};
  const documentTerm = terms.document ?? "病例";
  const documentQueueTerm = terms.document_queue ?? "病例队列";
  const uploadTerm = terms.upload ?? "上传病例 PDF / 图片 / 文本";
  const fieldResultsTerm = terms.field_results ?? "字段结果";
  const rawOcrItems = useMemo<DocumentFragment[]>(() => selectedCase?.ocr_blocks.map((block, index) => ({ ...block, reading_order: block.reading_order ?? index + 1, section_name: block.section_label ?? "智能文档解析", block_type: block.block_type ?? "line" as const, source_kind: "intelligent_document" as const })) ?? [], [selectedCase?.ocr_blocks]);
  const retrievalEvidenceItems = useMemo(() => (activeDiagnostics?.fragments ?? []).filter((fragment) => fragment.block_type !== "line"), [activeDiagnostics?.fragments]);
  const sourceEvidenceItems = useMemo<DocumentFragment[]>(() => {
    const boxes = (activeDiagnostics?.fragments ?? []).filter((f) => Array.isArray(f.bbox) && f.bbox.length >= 4);
    return boxes.length > 0 ? boxes : rawOcrItems;
  }, [activeDiagnostics?.fragments, rawOcrItems]);
  const evidenceItems = useMemo<DocumentFragment[]>(() => retrievalEvidenceItems.length ? retrievalEvidenceItems : rawOcrItems, [rawOcrItems, retrievalEvidenceItems]);
  const reviewDetailPending = Boolean(activeView === "review" && selectedCase && caseNeedsDetailHydration(selectedCase));
  const ocrRuntimeService = runtime?.runtime_settings.services?.ocr;
  const ocrRuntimeNotReady = Boolean(ocrRuntimeService && ocrRuntimeService.ready === false);
  const ocrRuntimeBannerTone = ocrRuntimeTone(ocrRuntimeService);

  // --- Field selection side effects ---
  useEffect(() => {
    if (selectedCase?.results.some((result) => result.field_key === selectedField)) return;
    const nextField = selectedCase?.results[0]?.field_key ?? fields[0]?.key ?? "";
    if (nextField !== selectedField) setSelectedField(nextField);
  }, [fields, selectedCase, selectedField]);
  useEffect(() => { if (activeResult) setReviewCode(activeResult.normalized_code ?? "unknown"); }, [activeResult?.field_key, activeResult?.normalized_code]);

  // --- Actions (extracted) ---
  const actions = useChartLensActions({ selectedCase, selectedId, cases, activeResult, reviewCode, reviewReason, documentTerm, setLoading, setError, setSelectedId });

  return {
    activeView, navigate, cases, fields, projectConfig, selectedCase, selectedId, setSelectedId,
    filter, setFilter, query, setQuery, selectedField, setSelectedField,
    reviewCode, setReviewCode, reviewReason, setReviewReason, loading, error,
    startupError, fieldDictionaryError, auth, runtime, diagnostics, diagnosticsLoading,
    activeDiagnostics, activeQuality, activeRun, fieldMap, filteredResults, activeResult,
    cacheHit, cachedInputTokens, latestModelLabel, latestModelName, modelRuntimeState,
    sidebarModelUsage, currentStatusLabel, authIdentity, sessionAccessLabel, sessionStateLabel,
    modelCredentialLabel, oauthConfigured, missingOauthConfig, oauthWarnings,
    rawOcrItems, evidenceItems, sourceEvidenceItems, reviewDetailPending,
    ocrRuntimeService, ocrRuntimeNotReady, ocrRuntimeBannerTone,
    documentTerm, documentQueueTerm, uploadTerm, fieldResultsTerm,
    ...actions
  };
}
