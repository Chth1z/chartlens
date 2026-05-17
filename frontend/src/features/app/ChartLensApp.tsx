import { Suspense, lazy, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Download,
  Eye,
  FileSearch,
  RefreshCw,
  Settings as SettingsIcon,
  Trash2,
  Upload
} from "lucide-react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
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
import type { AuthStatus, CaseDiagnostics, CaseRecord, DocumentFragment, FieldDefinition, ProjectConfig, RuntimeSettingsResponse } from "../../shared/types/api";
import { AuthLoading, LoginRequired } from "../auth/AuthGate";
import { EvidencePanel } from "../cases/EvidencePanel";
import { isWorkingStatus, modelAuthLabel, resultMatchesFilter, statusIcon, statusLabel, type FilterMode } from "../cases/status";
import { useCasePolling } from "../cases/useCasePolling";
import { DiagnosticsPage } from "../diagnostics/DiagnosticsPage";
import { DiagnosticsStrip } from "../diagnostics/DiagnosticsStrip";
import { ocrRuntimeSummary, ocrRuntimeTone } from "../diagnostics/ocrReadiness";
import { FieldResultsPanel } from "../review/FieldResultsPanel";
import { ReviewPanel } from "../review/ReviewPanel";
import { caseNeedsDetailHydration, diagnosticsForCase } from "./caseSwitching.js";

const SettingsPanel = lazy(() =>
  import("../settings/SettingsPanel").then((module) => ({ default: module.SettingsPanel }))
);

export function ChartLensApp() {
  const location = useLocation();
  const navigate = useNavigate();
  const routeCaseId = useMemo(() => {
    const match = location.pathname.match(/^\/cases\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }, [location.pathname]);
  const activeView = location.pathname.startsWith("/settings")
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

  if (auth?.enabled && !auth.authenticated) {
    return (
      <LoginRequired
        auth={auth}
        oauthConfigured={oauthConfigured}
        missingOauthConfig={missingOauthConfig}
        oauthWarnings={oauthWarnings}
      />
    );
  }

  if (startupError) {
    return (
      <main className="login-shell">
        <section className="login-panel">
          <div className="brand-mark"><AlertTriangle size={22} /></div>
          <h1>ChartLens</h1>
          <p>无法连接本地后端服务。</p>
          <div className="config-alert">
            <strong>服务不可用</strong>
            <small>{startupError}</small>
            <small>确认 `start.cmd` 已运行，并检查后端端口与 `VITE_API_BASE`。</small>
          </div>
        </section>
      </main>
    );
  }

  if (auth === null) {
    return <AuthLoading />;
  }

  const pageTitle =
    activeView === "settings"
      ? "设置"
      : activeView === "diagnostics"
        ? "处理日志"
        : activeView === "evals"
          ? "质量回归"
          : selectedCase?.case_id ?? "未选择病例";
  const pageSubtitle =
    activeView === "settings"
      ? "模型供应商、当前抽取链路、字段字典与本地维护。"
      : activeView === "diagnostics"
        ? "用于排查 OCR、缓存、模型调用和视觉兜底的处理记录。"
        : activeView === "evals"
          ? "基于金标准病例集的字段准确率回归，当前尚未开放入口。"
          : "脱敏 OCR 证据用于字段复核，原始文件保留在本机。";

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-label="ChartLens 病例结构化抽取">
          <div className="brand-mark"><FileSearch size={20} /></div>
          <div>
            <h1>ChartLens</h1>
            <p>病例结构化抽取</p>
          </div>
        </div>
        <label className={`upload-box ${loading ? "is-loading" : ""}`}>
          <Upload size={18} />
          <span>{loading ? "处理中..." : uploadTerm}</span>
          <input
            aria-label={`上传${documentTerm}文件`}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.txt"
            disabled={loading}
            onChange={(event) => void onUpload(event.target.files?.[0])}
          />
        </label>
        <nav className="workspace-tabs" aria-label="主导航">
          <NavLink className={activeView === "review" ? "active" : ""} to={selectedCase ? `/cases/${encodeURIComponent(selectedCase.case_id)}/review` : "/cases"}>
            <FileSearch size={16} /> 复核工作台
          </NavLink>
          <NavLink className={activeView === "diagnostics" ? "active" : ""} to="/diagnostics">
            <Eye size={16} /> 处理日志
          </NavLink>
          <NavLink className={activeView === "settings" ? "active" : ""} to="/settings">
            <SettingsIcon size={16} /> 设置
          </NavLink>
        </nav>
        <div className="queue-header">
          <span className="queue-title">{documentQueueTerm}</span>
          <small>{cases.length} 个</small>
        </div>
        <div className="case-list" aria-label={documentQueueTerm}>
          {cases.length === 0 && <div className="sidebar-empty">暂无{documentTerm}</div>}
          {cases.map((record) => (
            <div
              className={`case-row ${record.case_id === selectedCase?.case_id ? "selected" : ""}`}
              key={record.case_id}
            >
              <button
                aria-current={record.case_id === selectedCase?.case_id ? "true" : undefined}
                className="case-select"
                onClick={() => { setSelectedId(record.case_id); navigate(`/cases/${encodeURIComponent(record.case_id)}/review`); }}
                type="button"
              >
                <span className={`status-dot ${record.status}`}>{statusIcon(record.status)}</span>
                <span>
                  <strong>{record.case_id}</strong>
                  <small>{record.filename}</small>
                  <small>{statusLabel(record.status)}</small>
                </span>
              </button>
              <button
                aria-label={`从列表移除${documentTerm} ${record.case_id}`}
                className="case-delete"
                onClick={() => void removeCase(record.case_id)}
                disabled={loading}
                title="从列表移除并保留追溯数据"
                type="button"
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
        <div className="auth-card model-status-card">
          <div className="auth-card-head">
            <FileSearch size={15} />
            <span>当前抽取模型</span>
          </div>
          <strong>{latestModelName}</strong>
          <small>{latestModelLabel} / {modelRuntimeState}</small>
          <small>{sidebarModelUsage}</small>
          <small>访问：{sessionAccessLabel} / {sessionStateLabel}</small>
          <small>会话：{auth.session_auth.authenticated ? auth.session_auth.provider : "未登录"} / Cookie {auth.session_auth.cookie_name}</small>
          {auth.model_auth.token_cache_exists && <small>ChatGPT Token：已缓存</small>}
        </div>
      </aside>

      <section className={`workspace workspace-${activeView}`}>
        <header className="topbar">
          <div className="topbar-copy">
            <h2>{pageTitle}</h2>
            <p>{activeView === "review" && selectedCase ? `${currentStatusLabel}；` : ""}{pageSubtitle}</p>
          </div>
          <div className="topbar-actions">
            {activeView === "review" && selectedCase && (
              <button className="icon-button" onClick={() => void submitReprocess()} disabled={loading} title="按当前 OCR/字段配置重新处理" type="button">
                <RefreshCw size={16} /> 重新处理
              </button>
            )}
            {activeView === "review" && selectedCase && (
              <button className="icon-button" onClick={() => void approveVisionFallback()} disabled={loading} title="记录当前字段的图像兜底请求；只入库留痕，不会立即调用视觉模型" type="button">
                <Eye size={16} /> 记录图像兜底
              </button>
            )}
            {activeView === "review" && selectedCase && (
              <button className="icon-button primary" onClick={() => void submitExport()} disabled={loading} type="button">
                <Download size={16} /> 导出 Excel
              </button>
            )}
          </div>
        </header>

        {error && <div className="error-banner"><AlertTriangle size={16} /> {error}</div>}
        {ocrRuntimeNotReady && activeView !== "settings" && (
          <div className={`runtime-alert ${ocrRuntimeBannerTone === "danger" ? "danger" : "warning"}`}>
            <AlertTriangle size={16} />
            <div>
              <strong>{ocrRuntimeSummary(ocrRuntimeService)}</strong>
              {(ocrRuntimeService?.actions ?? []).slice(0, 2).map((action) => (
                <small key={`${action.label}-${action.command}`}>{action.label}：<code>{action.command}</code></small>
              ))}
            </div>
          </div>
        )}
        {fieldDictionaryError && activeView === "review" && (
          <div className="error-banner"><AlertTriangle size={16} /> 字段字典加载失败：{fieldDictionaryError}</div>
        )}

        {activeView === "settings" ? (
          <Suspense fallback={<SettingsPanelFallback />}>
            <SettingsPanel auth={auth} onAuthRefresh={async () => { await refreshAuthStatus(); }} onCasesCleared={clearLocalCases} />
          </Suspense>
        ) : activeView === "diagnostics" ? (
          <DiagnosticsPage
            selectedCase={selectedCase}
            activeQuality={activeQuality}
            activeRun={activeRun}
            diagnostics={diagnostics}
            diagnosticsLoading={diagnosticsLoading}
            cacheHit={cacheHit}
            cachedInputTokens={cachedInputTokens}
            latestModelLabel={latestModelLabel}
            documentTerm={documentTerm}
          />
        ) : activeView === "evals" ? (
          <section className="empty-workspace">
            <RefreshCw size={26} />
            <h3>质量回归暂未开放</h3>
            <p>该页面用于后续金标准病例集的准确率回归。未接入样本集前不作为日常工作入口。</p>
          </section>
        ) : selectedCase ? (
          <>
            <DiagnosticsStrip
              selectedCase={selectedCase}
              activeQuality={activeQuality}
              activeRun={activeRun}
              diagnostics={activeDiagnostics}
              diagnosticsLoading={diagnosticsLoading}
              cacheHit={cacheHit}
              cachedInputTokens={cachedInputTokens}
              latestModelLabel={latestModelLabel}
              ocrRuntimeService={ocrRuntimeService}
            />

            <div className={`review-grid ${reviewDetailPending ? "is-loading-detail" : ""}`}>
              {reviewDetailPending && <CaseDetailLoading caseId={selectedCase.case_id} />}
              <EvidencePanel
                caseId={selectedCase.case_id}
                evidenceItems={evidenceItems}
                sourceEvidenceItems={sourceEvidenceItems}
                activeResult={activeResult}
                activeFieldLabel={activeResult ? fieldMap.get(activeResult.field_key)?.label ?? activeResult.field_key : undefined}
                displayConfig={projectConfig?.document_profile.frontend}
              />
              <FieldResultsPanel
                filteredResults={filteredResults}
                fieldMap={fieldMap}
                title={fieldResultsTerm}
                filter={filter}
                query={query}
                selectedField={selectedField}
                setFilter={setFilter}
                setQuery={setQuery}
                setSelectedField={setSelectedField}
                setReviewCode={setReviewCode}
              />
              <ReviewPanel
                selectedCase={selectedCase}
                activeResult={activeResult}
                fieldMap={fieldMap}
                reviewCode={reviewCode}
                reviewReason={reviewReason}
                loading={loading}
                setReviewCode={setReviewCode}
                setReviewReason={setReviewReason}
                submitReview={submitReview}
              />
            </div>
          </>
        ) : (
          <section className="empty-workspace">
            <FileSearch size={26} />
            <h3>暂无{documentTerm}</h3>
            <p>上传 PDF、图片或文本后，这里会显示 OCR 证据、字段结果和复核面板。</p>
          </section>
        )}
      </section>
    </main>
  );
}

function SettingsPanelFallback() {
  return (
    <section className="settings-panel" aria-label="设置加载中">
      <div className="settings-card settings-loading">
        <RefreshCw size={16} className="spin" />
        <span>设置加载中...</span>
      </div>
    </section>
  );
}

function CaseDetailLoading({ caseId }: { caseId: string }) {
  return (
    <div className="case-detail-loading" role="status" aria-live="polite">
      <RefreshCw size={18} className="spin" />
      <strong>正在载入病例详情</strong>
      <span>{caseId}</span>
    </div>
  );
}

function mergeCaseRecord(next: CaseRecord, existing?: CaseRecord): CaseRecord {
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
