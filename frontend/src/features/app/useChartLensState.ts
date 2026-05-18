import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  deleteCase,
  downloadCaseExport,
  getAuthStatus,
  getCaseDocumentIr,
  getCaseDiagnostics,
  getCaseSourceOcr,
  getCaseResults,
  getFieldDictionary,
  getProjectConfig,
  getRuntimeSettings,
  listCases,
  reprocessCase,
  requestVisionFallback,
  updateReview,
  uploadCase
} from "../../shared/api/client";
import type {
  AuthStatus,
  CaseDiagnostics,
  CaseRecord,
  DocumentFragment,
  FieldDefinition,
  ProjectConfig,
  RuntimeSettingsResponse
} from "../../shared/types/api";
import { isWorkingStatus, modelAuthLabel, resultMatchesFilter, statusLabel, type FilterMode } from "../cases/status";
import { useCasePolling } from "../cases/useCasePolling";
import { ocrRuntimeTone } from "../diagnostics/ocrReadiness";
import { caseNeedsDetailHydration, diagnosticsForCase, mergeCaseRecord } from "./caseSwitching.js";

export type ActiveView = "review" | "diagnostics" | "settings" | "evals";

export type ChartLensState = ReturnType<typeof useChartLensState>;

export function useChartLensState() {
  const location = useLocation();
  const navigate = useNavigate();
  const routeCaseId = useMemo(() => {
    const match = location.pathname.match(/^\/cases\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }, [location.pathname]);
  const activeView: ActiveView = location.pathname.startsWith("/settings")
    ? "settings"
    : location.pathname.startsWith("/diagnostics")
      ? "diagnostics"
      : location.pathname.startsWith("/evals")
        ? "evals"
        : "review";

  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [fields, setFields] = useState<FieldDefinition[]>([]);
  const [projectConfig, setProjectConfig] = useState<ProjectConfig | null>(null);
  const [selectedId, setSelectedId] = useState(routeCaseId);
  const [filter, setFilter] = useState<FilterMode>("all");
  const [query, setQuery] = useState("");
  const [selectedField, setSelectedField] = useState<string>("");
  const [reviewCode, setReviewCode] = useState("1");
  const [reviewReason, setReviewReason] = useState("人工复核确认");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [fieldDictionaryError, setFieldDictionaryError] = useState<string | null>(null);
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [runtime, setRuntime] = useState<RuntimeSettingsResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<CaseDiagnostics | null>(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const diagnosticsRequestSeq = useRef(0);

  useEffect(() => {
    void bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (routeCaseId && routeCaseId !== selectedId) {
      setSelectedId(routeCaseId);
    }
  }, [routeCaseId, selectedId]);

  useEffect(() => {
    if (!["review", "diagnostics"].includes(activeView) || !selectedId || (auth?.enabled && !auth.authenticated)) {
      setDiagnostics(null);
      return;
    }
    void loadDiagnostics(selectedId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeView, selectedId, auth?.enabled, auth?.authenticated]);

  const selectedCase = useMemo(
    () => cases.find((item) => item.case_id === selectedId) ?? cases[0],
    [cases, selectedId]
  );
  const hasActiveJobs = useMemo(() => cases.some((record) => isWorkingStatus(record.status)), [cases]);
  const fieldMap = useMemo(() => new Map(fields.map((field) => [field.key, field])), [fields]);
  const authIdentity = auth?.session_auth.user?.email ?? auth?.user?.email ?? auth?.session_auth.user?.name ?? auth?.user?.name ?? "已登录用户";
  const sessionAccessLabel = auth?.enabled ? "应用会话" : "本机访问";
  const sessionStateLabel = auth?.enabled ? authIdentity : "无需 OAuth 登录";
  const modelCredentialLabel = auth?.model_auth.online_model_available
    ? `${modelAuthLabel(auth)} / API Key 已配置`
    : `${modelAuthLabel(auth)} / 本地回退或未配置凭据`;
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
      const matchesQuery = !normalizedQuery || text.toLowerCase().includes(normalizedQuery);
      const matchesFilter = resultMatchesFilter(result, filter);
      return matchesQuery && matchesFilter;
    });
  }, [selectedCase, fieldMap, normalizedQuery, filter]);
  const activeResult = useMemo(
    () => selectedCase?.results.find((item) => item.field_key === selectedField) ?? filteredResults[0],
    [filteredResults, selectedCase?.results, selectedField]
  );
  const activeDiagnostics = diagnosticsForCase(diagnostics, selectedCase?.case_id);
  const activeQuality = activeDiagnostics?.quality ?? selectedCase?.quality;
  const activeRun = activeDiagnostics?.latest_run ?? selectedCase?.latest_run ?? null;
  const cacheHit = Number(activeRun?.step_timings?.cache_hit ?? 0) > 0;
  const cachedInputTokens = activeRun?.cached_input_tokens ?? activeDiagnostics?.model_calls[0]?.cached_input_tokens ?? 0;
  const latestModelProvider = activeDiagnostics?.model_calls[0]?.provider;
  const latestModelLabel = modelAuthLabel(auth, latestModelProvider);
  const latestModelName = activeDiagnostics?.model_calls[0]?.model ?? activeRun?.llm_profile ?? "未记录";
  const modelRuntimeState = auth?.model_auth.online_model_available ? "API Key 已配置" : "本地回退或未配置凭据";
  const sidebarModelUsage = activeRun
    ? `调用 ${activeDiagnostics?.model_calls.length ?? 0} / tokens ${activeRun.input_tokens}:${cachedInputTokens}:${activeRun.output_tokens}`
    : "等待处理记录";
  const currentStatusLabel = selectedCase ? statusLabel(selectedCase.status) : "未选择";
  const terms = projectConfig?.app_profile.terms ?? {};
  const documentTerm = terms.document ?? "病例";
  const documentQueueTerm = terms.document_queue ?? "病例队列";
  const uploadTerm = terms.upload ?? "上传病例 PDF / 图片 / 文本";
  const fieldResultsTerm = terms.field_results ?? "字段结果";
  const rawOcrItems = useMemo<DocumentFragment[]>(
    () => selectedCase?.ocr_blocks.map((block, index) => ({
        ...block,
        reading_order: block.reading_order ?? index + 1,
        section_name: block.section_label ?? "智能文档解析",
        block_type: block.block_type ?? "line" as const,
        source_kind: "intelligent_document" as const
      })) ?? [],
    [selectedCase?.ocr_blocks]
  );
  const retrievalEvidenceItems = useMemo(
    () => (activeDiagnostics?.fragments ?? []).filter((fragment) => fragment.block_type !== "line"),
    [activeDiagnostics?.fragments]
  );
  const sourceEvidenceItems = useMemo<DocumentFragment[]>(
    () => {
      const diagnosticFragments = activeDiagnostics?.fragments ?? [];
      const diagnosticBoxes = diagnosticFragments.filter((fragment) => Array.isArray(fragment.bbox) && fragment.bbox.length >= 4);
      if (diagnosticBoxes.length > 0) return diagnosticBoxes;
      return rawOcrItems;
    },
    [activeDiagnostics?.fragments, rawOcrItems]
  );
  const evidenceItems = useMemo<DocumentFragment[]>(
    () => retrievalEvidenceItems.length ? retrievalEvidenceItems : rawOcrItems,
    [rawOcrItems, retrievalEvidenceItems]
  );
  const reviewDetailPending = Boolean(
    activeView === "review" &&
    selectedCase &&
    caseNeedsDetailHydration(selectedCase)
  );
  const ocrRuntimeService = runtime?.runtime_settings.services?.ocr;
  const ocrRuntimeNotReady = Boolean(ocrRuntimeService && ocrRuntimeService.ready === false);
  const ocrRuntimeBannerTone = ocrRuntimeTone(ocrRuntimeService);

  useEffect(() => {
    if (selectedCase?.results.some((result) => result.field_key === selectedField)) return;
    const nextField = selectedCase?.results[0]?.field_key ?? fields[0]?.key ?? "";
    if (nextField !== selectedField) {
      setSelectedField(nextField);
    }
  }, [fields, selectedCase, selectedField]);

  useEffect(() => {
    if (activeResult) {
      setReviewCode(activeResult.normalized_code ?? "unknown");
    }
  }, [activeResult?.field_key, activeResult?.normalized_code]);

  useCasePolling({ auth, hasActiveJobs, selectedId, refresh, loadDiagnostics });

  async function refreshAuthStatus() {
    const status = await getAuthStatus();
    setAuth(status);
    return status;
  }

  async function bootstrap() {
    let status: AuthStatus;
    try {
      status = await refreshAuthStatus();
      setStartupError(null);
    } catch (err) {
      setStartupError(err instanceof Error ? err.message : "无法连接后端服务");
      return;
    }
    if (!status.enabled || status.authenticated) {
      void loadRuntimeSettings();
      void refresh(status);
      void loadProjectConfig();
    }
  }

  async function loadRuntimeSettings() {
    try {
      setRuntime(await getRuntimeSettings());
    } catch {
      setRuntime(null);
    }
  }

  async function loadProjectConfig() {
    try {
      const config = await getProjectConfig();
      setProjectConfig(config);
      setFields(config.extraction_schema.fields);
      setFieldDictionaryError(null);
      setSelectedField((current) => config.extraction_schema.fields.some((field) => field.key === current) ? current : config.extraction_schema.fields[0]?.key ?? "");
    } catch (err) {
      await loadFieldDictionary(err instanceof Error ? err.message : "项目配置加载失败");
    }
  }

  async function loadFieldDictionary(prefix = "项目配置加载失败，字段字典兜底也失败") {
    try {
      const dictionary = await getFieldDictionary();
      setFields(dictionary.fields);
      setFieldDictionaryError(null);
      setSelectedField((current) => dictionary.fields.some((field) => field.key === current) ? current : dictionary.fields[0]?.key ?? "");
    } catch (err) {
      setFields([]);
      const detail = err instanceof Error ? err.message : "字段字典加载失败";
      setFieldDictionaryError(`${prefix}：${detail}`);
    }
  }

  async function refresh(currentAuth: AuthStatus | null = auth) {
    try {
      const remoteCases = await listCases();
      setCases((current) => remoteCases.map((remote) => mergeCaseRecord(remote, current.find((item) => item.case_id === remote.case_id))));
      setSelectedId((current) => {
        const next = routeCaseId || current;
        return remoteCases.some((item) => item.case_id === next) ? next : remoteCases[0]?.case_id ?? "";
      });
      if (remoteCases.length === 0) {
        setDiagnostics(null);
      }
    } catch (err) {
      if (currentAuth?.enabled || !currentAuth?.authenticated) {
        setError(err instanceof Error ? err.message : "获取病例失败");
      }
    }
  }

  async function loadDiagnostics(caseId: string, quiet = false) {
    const requestSeq = diagnosticsRequestSeq.current + 1;
    diagnosticsRequestSeq.current = requestSeq;
    if (!quiet) setDiagnosticsLoading(true);
    try {
      const [results, documentIr, sourceOcr, payload] = await Promise.all([
        getCaseResults(caseId),
        getCaseDocumentIr(caseId),
        getCaseSourceOcr(caseId),
        getCaseDiagnostics(caseId)
      ]);
      if (requestSeq !== diagnosticsRequestSeq.current) return;
      const ocrBlocks = sourceOcr.blocks.map((block, index) => ({
        ...block,
        reading_order: block.reading_order ?? index + 1
      }));
      setDiagnostics(payload);
      setCases((current) =>
        current.map((record) =>
          record.case_id === caseId
            ? {
                ...record,
                results,
                ocr_blocks: ocrBlocks,
                result_count: results.length,
                review_required_count: results.filter((result) => result.review_required).length,
                quality: payload.quality,
                latest_run: payload.latest_run,
                error_message: payload.latest_run?.error_message ?? null
              }
            : record
        )
      );
    } catch (err) {
      if (requestSeq !== diagnosticsRequestSeq.current) return;
      setDiagnostics(null);
      if (!quiet) {
        setError(err instanceof Error ? err.message : "获取诊断信息失败");
      }
    } finally {
      if (!quiet && requestSeq === diagnosticsRequestSeq.current) setDiagnosticsLoading(false);
    }
  }

  async function onUpload(file: File | undefined) {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const created = await uploadCase(file);
      setCases((current) => [created, ...current.filter((item) => item.case_id !== created.case_id)]);
      setSelectedId(created.case_id);
      navigate(`/cases/${encodeURIComponent(created.case_id)}/review`);
      void loadDiagnostics(created.case_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setLoading(false);
    }
  }

  async function submitReprocess() {
    if (!selectedCase) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await reprocessCase(selectedCase.case_id);
      setCases((current) => current.map((record) => record.case_id === updated.case_id ? mergeCaseRecord(updated, record) : record));
      await loadDiagnostics(updated.case_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新处理失败");
    } finally {
      setLoading(false);
    }
  }

  async function approveVisionFallback() {
    if (!selectedCase) return;
    setLoading(true);
    setError(null);
    try {
      await requestVisionFallback(selectedCase.case_id, {
        field_key: activeResult?.field_key ?? null,
        page: activeResult?.page ?? 1,
        bbox: activeResult?.bbox ?? [],
        reason: "人工确认当前字段页或裁剪区域已脱敏，记录为图像兜底请求。",
        reviewer: "local-reviewer",
        manual_redaction_confirmed: true
      });
      await loadDiagnostics(selectedCase.case_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "图像兜底请求记录失败");
    } finally {
      setLoading(false);
    }
  }

  async function submitExport() {
    if (!selectedCase) return;
    setLoading(true);
    setError(null);
    try {
      const { blob, filename } = await downloadCaseExport(selectedCase.case_id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Excel 导出失败");
    } finally {
      setLoading(false);
    }
  }

  const submitReview = useCallback(async () => {
    if (!selectedCase || !activeResult) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await updateReview(selectedCase.case_id, {
        field_key: activeResult.field_key,
        raw_value: reviewCode === "1" ? "有" : reviewCode === "0" ? "无" : reviewCode,
        normalized_code: reviewCode,
        comment: reviewReason,
        reviewer: "local-reviewer"
      });
      setCases((current) =>
        current.map((record) =>
          record.case_id === selectedCase.case_id
            ? {
                ...record,
                audit_count: record.audit_count + 1,
                results: record.results.map((result) => result.field_key === updated.field_key ? updated : result),
                review_required_count: record.results
                  .map((result) => result.field_key === updated.field_key ? updated : result)
                  .filter((result) => result.review_required).length
              }
            : record
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "复核提交失败");
    } finally {
      setLoading(false);
    }
  }, [activeResult, reviewCode, reviewReason, selectedCase]);

  async function removeCase(caseId: string) {
    const target = cases.find((record) => record.case_id === caseId);
    if (!target) return;
    if (!window.confirm(`从列表移除${documentTerm} ${target.case_id}？原始文件、抽取结果、人工复核和处理日志会保留，用于追溯。`)) return;
    setLoading(true);
    setError(null);
    try {
      await deleteCase(caseId);
      const nextCases = cases.filter((record) => record.case_id !== caseId);
      setCases(nextCases);
      if (selectedId === caseId) {
        setSelectedId(nextCases[0]?.case_id ?? "");
        setDiagnostics(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除病例失败");
    } finally {
      setLoading(false);
    }
  }

  function clearLocalCases() {
    setCases([]);
    setSelectedId("");
    setDiagnostics(null);
    navigate("/cases");
  }

  return {
    activeView,
    navigate,
    cases,
    fields,
    projectConfig,
    selectedCase,
    selectedId,
    setSelectedId,
    filter,
    setFilter,
    query,
    setQuery,
    selectedField,
    setSelectedField,
    reviewCode,
    setReviewCode,
    reviewReason,
    setReviewReason,
    loading,
    error,
    startupError,
    fieldDictionaryError,
    auth,
    runtime,
    diagnostics,
    diagnosticsLoading,
    activeDiagnostics,
    activeQuality,
    activeRun,
    fieldMap,
    filteredResults,
    activeResult,
    cacheHit,
    cachedInputTokens,
    latestModelLabel,
    latestModelName,
    modelRuntimeState,
    sidebarModelUsage,
    currentStatusLabel,
    authIdentity,
    sessionAccessLabel,
    sessionStateLabel,
    modelCredentialLabel,
    oauthConfigured,
    missingOauthConfig,
    oauthWarnings,
    rawOcrItems,
    evidenceItems,
    sourceEvidenceItems,
    reviewDetailPending,
    ocrRuntimeService,
    ocrRuntimeNotReady,
    ocrRuntimeBannerTone,
    documentTerm,
    documentQueueTerm,
    uploadTerm,
    fieldResultsTerm,
    refreshAuthStatus,
    onUpload,
    submitReprocess,
    approveVisionFallback,
    submitExport,
    submitReview,
    removeCase,
    clearLocalCases
  };
}
