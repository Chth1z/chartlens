import { Suspense, lazy } from "react";
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
import { NavLink } from "react-router-dom";
import { AuthLoading, LoginRequired } from "../auth/AuthGate";
import { EvidencePanel } from "../cases/EvidencePanel";
import { statusIcon, statusLabel } from "../cases/status";
import { DiagnosticsPage } from "../diagnostics/DiagnosticsPage";
import { DiagnosticsStrip } from "../diagnostics/DiagnosticsStrip";
import { ocrRuntimeSummary } from "../diagnostics/ocrReadiness";
import { FieldResultsPanel } from "../review/FieldResultsPanel";
import { ReviewPanel } from "../review/ReviewPanel";
import { CaseDetailLoading, SettingsPanelFallback } from "./components";
import { useChartLensState } from "./useChartLensState";

const SettingsPanel = lazy(() =>
  import("../settings/SettingsPanel").then((module) => ({ default: module.SettingsPanel }))
);

export function ChartLensApp() {
  const state = useChartLensState();
  const {
    activeView,
    navigate,
    cases,
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
    sessionAccessLabel,
    sessionStateLabel,
    oauthConfigured,
    missingOauthConfig,
    oauthWarnings,
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
  } = state;

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
        : selectedCase?.case_id ?? "未选择病例";
  const pageSubtitle =
    activeView === "settings"
      ? "模型供应商、当前抽取链路、字段字典与本地维护。"
      : activeView === "diagnostics"
        ? "用于排查 OCR、缓存、模型调用和视觉兜底的处理记录。"
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
