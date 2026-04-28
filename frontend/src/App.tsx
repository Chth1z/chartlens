import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Download,
  Eye,
  FileSearch,
  Filter,
  History,
  Layers,
  LogIn,
  LogOut,
  Loader2,
  RefreshCw,
  ScanLine,
  Search,
  ShieldCheck,
  Upload,
  XCircle
} from "lucide-react";
import {
  completeChatGptLogin,
  exportUrl,
  getAuthStatus,
  getCaseDiagnostics,
  getFieldDictionary,
  listCases,
  loginUrl,
  logoutUrl,
  reprocessCase,
  requestVisionFallback,
  updateReview,
  uploadCase
} from "./api";
import type { AuthStatus, CaseDiagnostics, CaseRecord, FieldDefinition, FieldResult } from "./types";

type FilterMode = "all" | "review" | "unknown" | "accepted";

const demoCases: CaseRecord[] = [
  {
    case_id: "CASE-DEMO",
    filename: "demo-case.txt",
    file_hash: "demo",
    status: "processed",
    error_message: null,
    created_at: new Date().toISOString(),
    audit_count: 1,
    ocr_blocks: [
      { page: 1, text: "性别：男 年龄：62岁", bbox: [0, 20, 500, 38], confidence: 0.98 },
      { page: 1, text: "既往史：高血压病史10年，2型糖尿病8年，否认脑卒中病史。", bbox: [0, 60, 780, 80], confidence: 0.96 },
      { page: 2, text: "手术记录：行动脉瘤夹闭术。出院情况：好转出院。", bbox: [0, 40, 760, 60], confidence: 0.94 }
    ],
    results: [
      {
        field_key: "gender",
        raw_value: "男",
        normalized_code: "1",
        confidence: 0.96,
        evidence_text: "性别：男 年龄：62岁",
        page: 1,
        bbox: [0, 20, 500, 38],
        reasoning_summary: "证据中直接出现男性。",
        review_required: false,
        error_code: null
      },
      {
        field_key: "hypertension_history",
        raw_value: "有",
        normalized_code: "1",
        confidence: 0.87,
        evidence_text: "既往史：高血压病史10年，2型糖尿病8年，否认脑卒中病史。",
        page: 1,
        bbox: [0, 60, 780, 80],
        reasoning_summary: "既往史明确提及。",
        review_required: true,
        error_code: null
      },
      {
        field_key: "stroke_history",
        raw_value: "无",
        normalized_code: "0",
        confidence: 0.72,
        evidence_text: "既往史：高血压病史10年，2型糖尿病8年，否认脑卒中病史。",
        page: 1,
        bbox: [0, 60, 780, 80],
        reasoning_summary: "存在否定表达，需要复核。",
        review_required: true,
        error_code: null
      }
    ],
    quality: {
      page_count: 2,
      ocr_block_count: 3,
      fragment_count: 3,
      avg_ocr_confidence: 0.96,
      low_confidence_block_count: 0,
      quality_band: "good",
      needs_vision_fallback: false
    },
    latest_run: {
      run_id: "RUN-DEMO",
      status: "completed",
      ocr_profile: "accurate",
      layout_profile: "chinese_inpatient_v1",
      llm_profile: "standard",
      parser_mode: "ocr",
      page_count: 2,
      ocr_block_count: 3,
      fragment_count: 3,
      avg_ocr_confidence: 0.96,
      low_confidence_block_count: 0,
      quality_band: "good",
      auto_accept_count: 1,
      review_required_count: 2,
      unknown_count: 0,
      input_tokens: 0,
      cached_input_tokens: 0,
      output_tokens: 0,
      cost_usd: 0,
      latency_ms: 420,
      step_timings: { ocr_ms: 160, fragment_ms: 20, rule_ms: 60 },
      error_message: null,
      created_at: new Date().toISOString(),
      completed_at: new Date().toISOString()
    }
  }
];

const demoDictionary: FieldDefinition[] = [
  { key: "gender", label: "性别", export_header: "性别(男1，女2)", allowed_codes: ["1", "2", "unknown"], phase: 1 },
  { key: "age", label: "年龄", export_header: "年龄", allowed_codes: ["integer", "unknown"], phase: 1 },
  { key: "hospital", label: "医院", export_header: "医院", allowed_codes: ["text", "unknown"], phase: 1 },
  { key: "hypertension_history", label: "高血压病史", export_header: "高血病史（有1，无0，不详）", allowed_codes: ["1", "0", "unknown"], phase: 1 },
  { key: "diabetes_history", label: "糖尿病史", export_header: "糖尿病史（有1，无0，不详）", allowed_codes: ["1", "0", "unknown"], phase: 1 },
  { key: "stroke_history", label: "卒中分组", export_header: "卒中分组（有：1；无：0）", allowed_codes: ["1", "0", "unknown"], phase: 1 }
];

function confidenceBand(result: FieldResult): FilterMode {
  if (result.review_required) return "review";
  if (result.normalized_code === "unknown" || result.error_code) return "unknown";
  return "accepted";
}

function isWorkingStatus(status: CaseRecord["status"]) {
  return status === "queued" || status === "processing" || status === "ocr" || status === "extracting";
}

function statusLabel(status: CaseRecord["status"]) {
  if (status === "queued") return "队列中";
  if (status === "processing") return "处理中";
  if (status === "ocr") return "OCR中";
  if (status === "extracting") return "抽取中";
  if (status === "processed") return "已完成";
  if (status === "degraded") return "已降级";
  return "失败";
}

function statusIcon(status: CaseRecord["status"]) {
  if (status === "processed") return <CheckCircle2 size={16} />;
  if (status === "degraded") return <AlertTriangle size={16} />;
  if (status === "failed") return <XCircle size={16} />;
  return <Loader2 size={16} className="spin" />;
}

function qualityText(band: string | undefined) {
  if (band === "good") return "良好";
  if (band === "fair") return "一般";
  if (band === "poor") return "较差";
  return "未知";
}

function formatMs(value: number | undefined) {
  if (!value) return "0 ms";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

function modelAuthLabel(auth: AuthStatus | null, provider?: string) {
  const activeProvider = provider || auth?.model_auth.provider;
  if (activeProvider === "openai_api_key" || activeProvider === "openai-responses") return "OpenAI API key";
  if (activeProvider === "chatgpt_codex" || activeProvider === "chatgpt-codex-responses") return "ChatGPT/Codex";
  return "本地规则 fallback";
}

export function App() {
  const [cases, setCases] = useState<CaseRecord[]>(demoCases);
  const [fields, setFields] = useState<FieldDefinition[]>(demoDictionary);
  const [selectedId, setSelectedId] = useState("CASE-DEMO");
  const [filter, setFilter] = useState<FilterMode>("all");
  const [query, setQuery] = useState("");
  const [selectedField, setSelectedField] = useState<string>("hypertension_history");
  const [reviewCode, setReviewCode] = useState("1");
  const [reviewReason, setReviewReason] = useState("人工复核确认");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [diagnostics, setDiagnostics] = useState<CaseDiagnostics | null>(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    if (!selectedId || selectedId === "CASE-DEMO" || (auth?.enabled && !auth.authenticated)) {
      setDiagnostics(null);
      return;
    }
    void loadDiagnostics(selectedId);
  }, [selectedId, auth?.enabled, auth?.authenticated]);

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
    const status = await getAuthStatus().catch(() => ({
      enabled: false,
      auth_provider: "chatgpt" as const,
      configured: true,
      missing_config: [],
      config_warnings: [],
      chatgpt_login_available: false,
      authenticated: true,
      user: null,
      model_auth: {
        auth_mode: "auto" as const,
        provider: "local_fallback" as const,
        online_model_available: false,
        api_key_configured: false,
        chatgpt_codex_configured: false
      }
    }));
    setAuth(status);
    if (authCompletionError && !status.authenticated) {
      setError(authCompletionError);
    }
    if (!status.enabled || status.authenticated) {
      void refresh();
    }
    getFieldDictionary()
      .then((dictionary) => setFields(dictionary.fields))
      .catch(() => setFields(demoDictionary));
  }

  const selectedCase = cases.find((item) => item.case_id === selectedId) ?? cases[0];
  const hasActiveJobs = useMemo(() => cases.some((record) => isWorkingStatus(record.status)), [cases]);
  const fieldMap = useMemo(() => new Map(fields.map((field) => [field.key, field])), [fields]);
  const authIdentity = auth?.user?.email ?? auth?.user?.name ?? "已登录用户";
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
  const modelOnline = auth?.model_auth.online_model_available ?? false;
  const evidenceItems = diagnostics?.fragments.length
    ? diagnostics.fragments
    : selectedCase?.ocr_blocks.map((block, index) => ({
        ...block,
        reading_order: index + 1,
        section_name: "OCR",
        block_type: "text" as const,
        source_kind: "ocr" as const
      })) ?? [];

  useEffect(() => {
    if (auth === null || (auth.enabled && !auth.authenticated) || !hasActiveJobs) return;
    const timer = window.setInterval(() => {
      void refresh();
      if (selectedId && selectedId !== "CASE-DEMO") {
        void loadDiagnostics(selectedId, true);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [auth, hasActiveJobs, selectedId]);

  async function refresh() {
    try {
      const remoteCases = await listCases();
      if (remoteCases.length > 0) {
        setCases(remoteCases);
        setSelectedId((current) => remoteCases.some((item) => item.case_id === current) ? current : remoteCases[0].case_id);
      }
    } catch (err) {
      if (auth?.enabled) {
        setError(err instanceof Error ? err.message : "获取病例失败");
      } else {
        setCases(demoCases);
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
      setCases((current) => [created, ...current.filter((item) => item.case_id !== "CASE-DEMO")]);
      setSelectedId(created.case_id);
      void loadDiagnostics(created.case_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setLoading(false);
    }
  }

  async function submitReprocess() {
    if (!selectedCase || selectedCase.case_id === "CASE-DEMO") return;
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
    if (!selectedCase || selectedCase.case_id === "CASE-DEMO") return;
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

  if (auth?.enabled && !auth.authenticated) {
    return (
      <main className="login-shell">
        <section className="login-panel">
          <div className="brand-mark"><FileSearch size={22} /></div>
          <h1>EYES</h1>
          <p>
            {oauthConfigured
              ? auth.auth_provider === "chatgpt"
                ? "病例结构化抽取系统已启用 ChatGPT 登录，请在浏览器中完成验证。"
                : "病例结构化抽取系统已启用 OAuth 验证，请登录后继续。"
              : "OAuth 已启用，但后端登录参数尚未配置完整。"}
          </p>
          {!oauthConfigured && (
            <div className="config-alert">
              <strong>缺少配置</strong>
              {missingOauthConfig.map((item) => <code key={item}>{item}</code>)}
              <small>补齐 `.env` 后运行 `stop.cmd` 和 `start.cmd`，或将 `EYES_OAUTH_ENABLED=false` 切回本地模式。</small>
            </div>
          )}
          {oauthWarnings.length > 0 && (
            <div className="config-alert warning">
              <strong>配置提醒</strong>
              {oauthWarnings.map((item) => <small key={item}>{item}</small>)}
            </div>
          )}
          {oauthConfigured ? (
            <a className="icon-button primary full" href={loginUrl("/")}>
              <LogIn size={16} /> {auth.auth_provider === "chatgpt" ? "使用 ChatGPT 登录" : "使用 OAuth 登录"}
            </a>
          ) : (
            <button className="icon-button primary full" disabled>
              <AlertTriangle size={16} /> OAuth 配置不完整
            </button>
          )}
        </section>
      </main>
    );
  }

  if (auth === null) {
    return (
      <main className="login-shell">
        <section className="login-panel">
          <div className="brand-mark"><Loader2 size={22} className="spin" /></div>
          <h1>EYES</h1>
          <p>正在检查本地服务和登录状态。</p>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><FileSearch size={20} /></div>
          <div>
            <h1>EYES</h1>
            <p>病例结构化抽取</p>
          </div>
        </div>
        <label className="upload-box">
          <Upload size={18} />
          <span>{loading ? "处理中..." : "上传病例 PDF / 图片 / 文本"}</span>
          <input type="file" accept=".pdf,.png,.jpg,.jpeg,.txt" onChange={(event) => void onUpload(event.target.files?.[0])} />
        </label>
        <div className="queue-title">病例队列</div>
        <div className="case-list">
          {cases.map((record) => (
            <button
              className={`case-row ${record.case_id === selectedCase?.case_id ? "selected" : ""}`}
              key={record.case_id}
              onClick={() => setSelectedId(record.case_id)}
            >
              <span className={`status-dot ${record.status}`}>{statusIcon(record.status)}</span>
              <span>
                <strong>{record.case_id}</strong>
                <small>{record.filename}</small>
                <small>{statusLabel(record.status)}</small>
              </span>
            </button>
          ))}
        </div>
        <div className="auth-card">
          <div className="auth-card-head">
            <ShieldCheck size={15} />
            <span>{auth.enabled ? "OAuth 验证" : "本地模式"}</span>
          </div>
          <strong>{auth.enabled ? authIdentity : "OAuth 未启用"}</strong>
          <small>{auth.enabled ? "当前会话已通过登录验证" : "本机试用模式，未要求登录"}</small>
          <small>模型通道：{modelAuthLabel(auth)}</small>
          {auth.enabled && auth.authenticated && (
            <a className="icon-button full" href={logoutUrl()} title="退出登录">
              <LogOut size={16} /> 退出登录
            </a>
          )}
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h2>{selectedCase?.case_id ?? "未选择病例"}</h2>
            <p>
              {selectedCase ? `${statusLabel(selectedCase.status)}；` : ""}
              {modelOnline ? `在线模型通道：${modelAuthLabel(auth)}；仅发送脱敏 OCR 证据。` : "当前为本地规则 fallback，未使用在线模型。"}
            </p>
          </div>
          <div className="topbar-actions">
            <span className="security"><ShieldCheck size={16} /> 本地脱敏</span>
            {auth?.enabled && auth.authenticated && (
              <a className="icon-button" href={logoutUrl()} title="退出登录">
                <LogOut size={16} /> {authIdentity}
              </a>
            )}
            {selectedCase && selectedCase.case_id !== "CASE-DEMO" && (
              <button className="icon-button" onClick={() => void submitReprocess()} disabled={loading} title="按当前 OCR/字段配置重新处理">
                <RefreshCw size={16} /> 重新处理
              </button>
            )}
            {selectedCase && selectedCase.case_id !== "CASE-DEMO" && (
              <button className="icon-button" onClick={() => void approveVisionFallback()} disabled={loading} title="记录人工批准后的视觉兜底请求">
                <Eye size={16} /> 批准视觉兜底
              </button>
            )}
            {selectedCase && selectedCase.case_id !== "CASE-DEMO" && (
              <a className="icon-button primary" href={exportUrl(selectedCase.case_id)}>
                <Download size={16} /> 导出 Excel
              </a>
            )}
          </div>
        </header>

        {error && <div className="error-banner"><AlertTriangle size={16} /> {error}</div>}

        <section className="diagnostics-strip">
          <div className={`metric-card status-${selectedCase?.status ?? "queued"}`}>
            <span><RefreshCw size={16} /> 处理状态</span>
            <strong>{selectedCase ? statusLabel(selectedCase.status) : "未选择"}</strong>
            <small>{selectedCase?.error_message ?? (selectedCase && isWorkingStatus(selectedCase.status) ? "后台任务运行中，界面自动刷新" : "任务已结束")}</small>
          </div>
          <div className={`metric-card quality-${activeQuality?.quality_band ?? "poor"}`}>
            <span><ScanLine size={16} /> OCR 质量</span>
            <strong>{qualityText(activeQuality?.quality_band)}</strong>
            <small>
              {activeQuality?.ocr_block_count ?? 0} 行 / {activeQuality?.fragment_count ?? 0} 段，低置信 {activeQuality?.low_confidence_block_count ?? 0}
              {cacheHit ? "，缓存命中" : ""}
            </small>
          </div>
          <div className="metric-card">
            <span><Layers size={16} /> 版面分割</span>
            <strong>{activeRun?.layout_profile ?? "chinese_inpatient_v1"}</strong>
            <small>{diagnosticsLoading ? "正在刷新诊断..." : `${diagnostics?.fragments.length ?? 0} 个章节片段`}</small>
          </div>
          <div className="metric-card">
            <span><Clock3 size={16} /> 处理耗时</span>
            <strong>{formatMs(activeRun?.latency_ms)}</strong>
            <small>OCR {formatMs(activeRun?.step_timings?.ocr_ms)}，规则 {formatMs(activeRun?.step_timings?.rule_ms)}</small>
          </div>
          <div className="metric-card">
            <span><FileSearch size={16} /> LLM 调用</span>
            <strong>{diagnostics?.model_calls.length ?? 0}</strong>
            <small>{latestModelLabel}，输入 {activeRun?.input_tokens ?? 0} / 缓存 {cachedInputTokens} / 输出 {activeRun?.output_tokens ?? 0} tokens</small>
          </div>
        </section>

        <div className="review-grid">
          <section className="document-panel">
            <div className="panel-title">
              <span>脱敏证据与章节视图</span>
              <small>{evidenceItems.length} 条片段</small>
            </div>
            <div className="document-page">
              {evidenceItems.map((block, index) => {
                const highlighted = activeResult?.evidence_text === block.text;
                return (
                  <button className={`evidence-line ${highlighted ? "active" : ""}`} key={`${block.page}-${index}`}>
                    <span>p.{block.page}</span>
                    <p><mark>{block.section_name}</mark>{block.text}</p>
                    <em>{Math.round(block.confidence * 100)}%</em>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="fields-panel">
            <div className="field-toolbar">
              <div className="search-box">
                <Search size={16} />
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索字段或证据" />
              </div>
              <div className="filter-tabs" aria-label="字段筛选">
                {[
                  ["all", "全部"],
                  ["review", "需复核"],
                  ["unknown", "缺失"],
                  ["accepted", "已确认"]
                ].map(([key, label]) => (
                  <button className={filter === key ? "active" : ""} key={key} onClick={() => setFilter(key as FilterMode)}>
                    {key === "all" && <Filter size={14} />}
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="field-table">
              <div className="field-row header">
                <span>字段</span>
                <span>编码</span>
                <span>置信度</span>
                <span>状态</span>
              </div>
              {filteredResults.map((result) => {
                const field = fieldMap.get(result.field_key);
                const band = confidenceBand(result);
                return (
                  <button
                    className={`field-row ${selectedField === result.field_key ? "selected" : ""}`}
                    key={result.field_key}
                    onClick={() => {
                      setSelectedField(result.field_key);
                      setReviewCode(result.normalized_code ?? "unknown");
                    }}
                  >
                    <span>
                      <strong>{field?.label ?? result.field_key}</strong>
                      <small>{field?.export_header ?? result.field_key}</small>
                    </span>
                    <span>{result.normalized_code ?? "unknown"}</span>
                    <span>
                      <i style={{ width: `${Math.max(6, result.confidence * 100)}%` }} />
                      {Math.round(result.confidence * 100)}%
                    </span>
                    <span className={`badge ${band}`}>{band === "accepted" ? "自动填入" : band === "review" ? "需复核" : "不详"}</span>
                  </button>
                );
              })}
            </div>
          </section>

          <aside className="audit-panel">
            <div className="panel-title">
              <span>复核与审计</span>
              <small><History size={14} /> {selectedCase?.audit_count ?? 0} 次修改</small>
            </div>
            {activeResult ? (
              <div className="review-card">
                <h3>{fieldMap.get(activeResult.field_key)?.label ?? activeResult.field_key}</h3>
                <dl>
                  <dt>当前值</dt>
                  <dd>{activeResult.raw_value ?? "不详"} / {activeResult.normalized_code ?? "unknown"}</dd>
                  <dt>证据</dt>
                  <dd>{activeResult.evidence_text ?? "未找到证据"}</dd>
                  <dt>模型说明</dt>
                  <dd>{activeResult.reasoning_summary ?? "无"}</dd>
                </dl>
                <label>
                  复核编码
                  <input value={reviewCode} onChange={(event) => setReviewCode(event.target.value)} />
                </label>
                <label>
                  修改原因
                  <textarea value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} />
                </label>
                <button className="icon-button primary full" onClick={() => void submitReview()} disabled={loading}>
                  <CheckCircle2 size={16} /> 确认复核
                </button>
              </div>
            ) : (
              <div className="empty-state">没有可复核字段</div>
            )}
          </aside>
        </div>
      </section>
    </main>
  );
}
