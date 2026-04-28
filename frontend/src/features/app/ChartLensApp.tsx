import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Download,
  Eye,
  FileSearch,
  LogOut,
  RefreshCw,
  Settings as SettingsIcon,
  ShieldCheck,
  Trash2,
  Upload
} from "lucide-react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  completeChatGptLogin,
  deleteCase,
  exportUrl,
  getAuthStatus,
  getCaseDiagnostics,
  getFieldDictionary,
  listCases,
  logoutUrl,
  reprocessCase,
  requestVisionFallback,
  updateReview,
  uploadCase
} from "../../shared/api/client";
import type { AuthStatus, CaseDiagnostics, CaseRecord, DocumentFragment, FieldDefinition } from "../../shared/types/api";
import { AuthLoading, LoginRequired } from "../auth/AuthGate";
import { EvidencePanel } from "../cases/EvidencePanel";
import { confidenceBand, isWorkingStatus, modelAuthLabel, statusIcon, statusLabel, type FilterMode } from "../cases/status";
import { useCasePolling } from "../cases/useCasePolling";
import { DiagnosticsStrip } from "../diagnostics/DiagnosticsStrip";
import { FieldResultsPanel } from "../review/FieldResultsPanel";
import { ReviewPanel } from "../review/ReviewPanel";
import { SettingsPanel } from "../settings/SettingsPanel";

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
  const [diagnostics, setDiagnostics] = useState<CaseDiagnostics | null>(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);

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

  const selectedCase = cases.find((item) => item.case_id === selectedId) ?? cases[0];
  const hasActiveJobs = useMemo(() => cases.some((record) => isWorkingStatus(record.status)), [cases]);
  const fieldMap = useMemo(() => new Map(fields.map((field) => [field.key, field])), [fields]);
  const authIdentity = auth?.session_auth.user?.email ?? auth?.user?.email ?? auth?.session_auth.user?.name ?? auth?.user?.name ?? "已登录用户";
  const oauthConfigured = auth?.configured ?? true;
  const missingOauthConfig = auth?.missing_config ?? [];
  const oauthWarnings = auth?.config_warnings ?? [];
  const filteredResults = useMemo(() => {
    if (!selectedCase) return [];
    return selectedCase.results.filter((result) => {
      const field = fieldMap.get(result.field_key);
      const text = `${field?.label ?? result.field_key} ${result.raw_value ?? ""} ${result.evidence_text ?? ""}`;
      const matchesQuery = !query || text.toLowerCase().includes(query.toLowerCase());
      const matchesFilter = filter === "all" || confidenceBand(result) === filter;
      return matchesQuery && matchesFilter;
    });
  }, [selectedCase, fieldMap, query, filter]);
  const activeResult = selectedCase?.results.find((item) => item.field_key === selectedField) ?? filteredResults[0];
  const activeQuality = diagnostics?.quality ?? selectedCase?.quality;
  const activeRun = diagnostics?.latest_run ?? selectedCase?.latest_run ?? null;
  const cacheHit = Number(activeRun?.step_timings?.cache_hit ?? 0) > 0;
  const cachedInputTokens = activeRun?.cached_input_tokens ?? diagnostics?.model_calls[0]?.cached_input_tokens ?? 0;
  const latestModelProvider = diagnostics?.model_calls[0]?.provider;
  const latestModelLabel = modelAuthLabel(auth, latestModelProvider);
  const currentStatusLabel = selectedCase ? statusLabel(selectedCase.status) : "未选择";
  const rawOcrItems: DocumentFragment[] =
    selectedCase?.ocr_blocks.map((block, index) => ({
        ...block,
        reading_order: index + 1,
        section_name: "OCR 原文",
        block_type: "line" as const,
        source_kind: "ocr" as const
      })) ?? [];
  const retrievalEvidenceItems = (diagnostics?.fragments ?? []).filter((fragment) => fragment.block_type !== "line");
  const evidenceItems: DocumentFragment[] = retrievalEvidenceItems.length ? retrievalEvidenceItems : rawOcrItems;

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
    const url = new URL(window.location.href);
    const ticket = url.pathname === "/auth/complete" ? url.searchParams.get("ticket") : null;
    let authCompletionError: string | null = null;
    if (ticket) {
      try {
        const completed = await completeChatGptLogin(ticket);
        window.history.replaceState({}, "", completed.next || "/");
      } catch (err) {
        authCompletionError = err instanceof Error ? err.message : "ChatGPT 登录完成失败";
        window.history.replaceState({}, "", "/");
      }
    }
    let status: AuthStatus;
    try {
      status = await refreshAuthStatus();
      setStartupError(null);
    } catch (err) {
      setStartupError(err instanceof Error ? err.message : "无法连接后端服务");
      return;
    }
    if (authCompletionError && !status.authenticated) {
      setError(authCompletionError);
    }
    if (!status.enabled || status.authenticated) {
      void refresh(status);
      void loadFieldDictionary();
    }
  }

  async function loadFieldDictionary() {
    try {
      const dictionary = await getFieldDictionary();
      setFields(dictionary.fields);
      setFieldDictionaryError(null);
      setSelectedField((current) => dictionary.fields.some((field) => field.key === current) ? current : dictionary.fields[0]?.key ?? "");
    } catch (err) {
      setFields([]);
      setFieldDictionaryError(err instanceof Error ? err.message : "字段字典加载失败");
    }
  }

  async function refresh(currentAuth: AuthStatus | null = auth) {
    try {
      const remoteCases = await listCases();
      setCases(remoteCases);
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
    if (!quiet) setDiagnosticsLoading(true);
    try {
      const payload = await getCaseDiagnostics(caseId);
      setDiagnostics(payload);
    } catch (err) {
      setDiagnostics(null);
      if (!quiet && auth?.enabled) {
        setError(err instanceof Error ? err.message : "获取诊断信息失败");
      }
    } finally {
      if (!quiet) setDiagnosticsLoading(false);
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
      setCases((current) => current.map((record) => record.case_id === updated.case_id ? updated : record));
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
        page: activeResult?.page ?? 1,
        bbox: activeResult?.bbox ?? [],
        reason: "人工确认低质量页或裁剪区域已脱敏，可进入视觉兜底队列。",
        reviewer: "local-reviewer",
        manual_redaction_confirmed: true
      });
      await loadDiagnostics(selectedCase.case_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "视觉兜底批准失败");
    } finally {
      setLoading(false);
    }
  }

  async function submitReview() {
    if (!selectedCase || !activeResult) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await updateReview(selectedCase.case_id, {
        field_key: activeResult.field_key,
        new_raw_value: reviewCode === "1" ? "有" : reviewCode === "0" ? "无" : reviewCode,
        new_normalized_code: reviewCode,
        reason: reviewReason,
        reviewer: "local-reviewer"
      });
      setCases((current) =>
        current.map((record) =>
          record.case_id === selectedCase.case_id
            ? {
                ...record,
                audit_count: record.audit_count + 1,
                results: record.results.map((result) => result.field_key === updated.field_key ? updated : result)
              }
            : record
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "复核提交失败");
    } finally {
      setLoading(false);
    }
  }

  async function removeCase(caseId: string) {
    const target = cases.find((record) => record.case_id === caseId);
    if (!target) return;
    if (!window.confirm(`删除病例 ${target.case_id}？相关抽取结果、复核记录和运行日志会一起删除。`)) return;
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
      ? "系统配置、字段字典、账号凭据与本地数据清理。"
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
          <span>{loading ? "处理中..." : "上传病例 PDF / 图片 / 文本"}</span>
          <input
            aria-label="上传病例文件"
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
          <span className="queue-title">病例队列</span>
          <small>{cases.length} 个</small>
        </div>
        <div className="case-list" aria-label="病例队列">
          {cases.length === 0 && <div className="sidebar-empty">暂无病例</div>}
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
                aria-label={`删除病例 ${record.case_id}`}
                className="case-delete"
                onClick={() => void removeCase(record.case_id)}
                disabled={loading}
                title="删除病例"
                type="button"
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
        <div className="auth-card">
          <div className="auth-card-head">
            <ShieldCheck size={15} />
            <span>{auth.enabled ? "应用会话" : "本地模式"}</span>
          </div>
          <strong>{auth.enabled ? authIdentity : "OAuth 未启用"}</strong>
          <small>{auth.session_auth.authenticated ? `Cookie：${auth.session_auth.cookie_name}` : "未登录"}</small>
          <small>模型通道：{modelAuthLabel(auth)}；token {auth.model_auth.token_cache_exists ? "存在" : "不存在"}</small>
          {auth.enabled && auth.authenticated && (
            <a className="icon-button full" href={logoutUrl()} title="退出登录">
              <LogOut size={16} /> 退出登录
            </a>
          )}
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="topbar-copy">
            <h2>{pageTitle}</h2>
            <p>{activeView === "review" && selectedCase ? `${currentStatusLabel}；` : ""}{pageSubtitle}</p>
          </div>
          <div className="topbar-actions">
            <span className="security"><ShieldCheck size={16} /> 本地脱敏</span>
            {activeView === "review" && selectedCase && (
              <a className="icon-button primary" href={exportUrl(selectedCase.case_id)}>
                <Download size={16} /> 导出 Excel
              </a>
            )}
            {activeView === "review" && selectedCase && (
              <button className="icon-button" onClick={() => void submitReprocess()} disabled={loading} title="按当前 OCR/字段配置重新处理" type="button">
                <RefreshCw size={16} /> 重新处理
              </button>
            )}
            {activeView === "review" && selectedCase && (
              <button className="icon-button" onClick={() => void approveVisionFallback()} disabled={loading} title="记录人工确认后的视觉复核请求" type="button">
                <Eye size={16} /> 视觉复核
              </button>
            )}
          </div>
        </header>

        {error && <div className="error-banner"><AlertTriangle size={16} /> {error}</div>}
        {fieldDictionaryError && activeView === "review" && (
          <div className="error-banner"><AlertTriangle size={16} /> 字段字典加载失败：{fieldDictionaryError}</div>
        )}

        {activeView === "settings" ? (
          <SettingsPanel auth={auth} onAuthRefresh={async () => { await refreshAuthStatus(); }} onCasesCleared={clearLocalCases} />
        ) : activeView === "diagnostics" ? (
          selectedCase ? (
            <section className="route-panel">
              <DiagnosticsStrip
                selectedCase={selectedCase}
                activeQuality={activeQuality}
                activeRun={activeRun}
                diagnostics={diagnostics}
                diagnosticsLoading={diagnosticsLoading}
                cacheHit={cacheHit}
                cachedInputTokens={cachedInputTokens}
                latestModelLabel={latestModelLabel}
              />
              <div className="settings-card">
                <div className="settings-card-title">
                  <Eye size={18} />
                  <span>最近处理运行</span>
                </div>
                <dl className="settings-dl">
                  <dt>病例</dt>
                  <dd>{selectedCase.case_id}</dd>
                  <dt>配置版本</dt>
                  <dd>{activeRun?.system_config_version ?? "未知"}</dd>
                  <dt>字段字典</dt>
                  <dd>{activeRun?.field_dictionary_version ?? "未知"}</dd>
                  <dt>模型调用</dt>
                  <dd>{diagnostics?.model_calls.length ?? 0}</dd>
                  <dt>视觉兜底</dt>
                  <dd>{diagnostics?.vision_requests.length ?? 0}</dd>
                </dl>
              </div>
            </section>
          ) : (
            <section className="empty-workspace">
              <Eye size={26} />
              <h3>暂无诊断数据</h3>
              <p>上传并处理病例后，这里会显示质量、配置版本和模型调用记录。</p>
            </section>
          )
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
              diagnostics={diagnostics}
              diagnosticsLoading={diagnosticsLoading}
              cacheHit={cacheHit}
              cachedInputTokens={cachedInputTokens}
              latestModelLabel={latestModelLabel}
            />

            <div className="review-grid">
              <EvidencePanel
                evidenceItems={evidenceItems}
                activeResult={activeResult}
                activeFieldLabel={activeResult ? fieldMap.get(activeResult.field_key)?.label ?? activeResult.field_key : undefined}
              />
              <FieldResultsPanel
                filteredResults={filteredResults}
                fieldMap={fieldMap}
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
            <h3>暂无病例</h3>
            <p>上传 PDF、图片或文本后，这里会显示 OCR 证据、字段结果和复核面板。</p>
          </section>
        )}
      </section>
    </main>
  );
}
