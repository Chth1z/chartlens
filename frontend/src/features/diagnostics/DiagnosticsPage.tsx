import { Activity, AlertTriangle, BrainCircuit, Clock3, Eye, FileText, Layers, Route, ScanText } from "lucide-react";
import type { CaseDiagnostics, CaseRecord, DocumentFragment, OcrQuality, ProcessingRun, VisionFallbackRecord } from "../../shared/types/api";
import { qualityText, statusLabel } from "../cases/status";
import { DiagnosticsStrip } from "./DiagnosticsStrip";
import { buildDiagnosticsTimeline, formatDuration, formatTimestamp, formatTokenSummary, summarizeModelCalls } from "./diagnosticsLog";

interface DiagnosticsPageProps {
  selectedCase?: CaseRecord;
  activeQuality?: OcrQuality;
  activeRun: ProcessingRun | null;
  diagnostics: CaseDiagnostics | null;
  diagnosticsLoading: boolean;
  cacheHit: boolean;
  cachedInputTokens: number;
  latestModelLabel: string;
  documentTerm: string;
}

export function DiagnosticsPage({
  selectedCase,
  activeQuality,
  activeRun,
  diagnostics,
  diagnosticsLoading,
  cacheHit,
  cachedInputTokens,
  latestModelLabel,
  documentTerm
}: DiagnosticsPageProps) {
  if (!selectedCase) {
    return (
      <section className="empty-workspace">
        <Eye size={26} />
        <h3>暂无诊断数据</h3>
        <p>上传并处理病例后，这里会显示质量、配置版本和模型调用记录。</p>
      </section>
    );
  }

  const runs = diagnostics?.runs ?? (activeRun ? [activeRun] : []);
  const timeline = buildDiagnosticsTimeline(runs, activeRun?.run_id);
  const modelSummary = summarizeModelCalls(diagnostics?.model_calls ?? []);
  const fragmentSummary = summarizeFragments(diagnostics?.fragments ?? []);
  const visionRequests = diagnostics?.vision_requests ?? [];

  return (
    <section className="diagnostics-page">
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

      <div className="log-overview" aria-label="诊断概览">
        <div className="log-metric">
          <FileText size={18} />
          <span>{documentTerm}</span>
          <strong>{selectedCase.case_id}</strong>
          <small>{statusLabel(selectedCase.status)} / {selectedCase.filename}</small>
        </div>
        <div className="log-metric">
          <ScanText size={18} />
          <span>文档质量</span>
          <strong>{qualityText(activeQuality?.quality_band)}</strong>
          <small>{activeQuality?.page_count ?? activeRun?.page_count ?? 0} 页 / {activeQuality?.ocr_block_count ?? activeRun?.ocr_block_count ?? 0} 块</small>
        </div>
        <div className="log-metric">
          <BrainCircuit size={18} />
          <span>模型调用</span>
          <strong>{modelSummary.totalCalls} 条</strong>
          <small>{modelSummary.failedCalls} 失败 / tokens {modelSummary.hasTokenData ? modelSummary.totalTokens : "未记录"} / {modelSummary.costLabel}</small>
        </div>
        <div className="log-metric">
          <Route size={18} />
          <span>运行记录</span>
          <strong>{diagnostics?.run_count ?? timeline.length} 次</strong>
          <small>{activeRun ? `${activeRun.system_config_version ?? "未知配置"} / ${formatDuration(activeRun.latency_ms)}` : "暂无运行"}</small>
        </div>
      </div>

      <div className="diagnostics-workbench">
        <section className="log-panel log-panel-timeline">
          <div className="log-panel-title">
            <span><Activity size={17} /> 运行时间线</span>
            <small>{timeline.length} 次</small>
          </div>
          <div className="run-timeline">
            {timeline.map((run) => (
              <article className={`run-card tone-${run.tone}`} key={run.runId}>
                <div className="run-card-head">
                  <span>{run.isLatest ? "LATEST" : run.shortRunId}</span>
                  <strong>{run.status}</strong>
                </div>
                <dl>
                  <dt>创建</dt>
                  <dd>{run.createdLabel}</dd>
                  <dt>完成</dt>
                  <dd>{run.completedLabel}</dd>
                  <dt>链路</dt>
                  <dd>{run.profileLabel}</dd>
                  <dt>字段</dt>
                  <dd>{run.fieldSummary}</dd>
                  <dt>文档</dt>
                  <dd>{run.documentSummary}</dd>
                  <dt>Tokens</dt>
                  <dd>{run.tokenSummary}</dd>
                </dl>
                {run.errorMessage && (
                  <p className="run-error"><AlertTriangle size={14} /> {run.errorMessage}</p>
                )}
              </article>
            ))}
            {timeline.length === 0 && <div className="empty-state">暂无处理运行</div>}
          </div>
        </section>

        <section className="log-panel log-panel-wide">
          <div className="log-panel-title">
            <span><BrainCircuit size={17} /> 模型调用</span>
            <small>{modelSummary.totalCalls} 条 / {modelSummary.hasLatencyData ? formatDuration(modelSummary.latencyMs) : "耗时未记录"}</small>
          </div>
          <div className="log-table" role="table" aria-label="模型调用日志">
            <div className="log-table-row header" role="row">
              <span>模型</span>
              <span>字段</span>
              <span>Tokens</span>
              <span>耗时</span>
              <span>状态</span>
            </div>
            {(diagnostics?.model_calls ?? []).map((call) => (
              <div className="log-table-row" role="row" key={call.call_id}>
                <span>
                  <strong>{call.provider}</strong>
                  <small>{call.model} / {call.mode}</small>
                </span>
                <span>{formatFieldKeys(call.field_keys)}</span>
                <span>{formatTokenSummary(call.input_tokens, call.cached_input_tokens, call.output_tokens)}</span>
                <span>{formatDuration(call.latency_ms)}</span>
                <span>
                  <span className={`log-status ${call.error_code || call.status !== "completed" ? "error" : "ok"}`}>
                    {call.error_code ?? call.status}
                  </span>
                  {!!call.fallback_errors?.length && (
                    <small className="log-error-detail">{call.fallback_errors[0]}</small>
                  )}
                </span>
              </div>
            ))}
            {!diagnostics?.model_calls.length && <div className="empty-state">暂无模型调用日志</div>}
          </div>
        </section>

        <section className="log-panel">
          <div className="log-panel-title">
            <span><Layers size={17} /> 片段概览</span>
            <small>{diagnostics?.fragments.length ?? 0} 段</small>
          </div>
          <div className="fragment-summary">
            {fragmentSummary.map((item) => (
              <div className="fragment-summary-row" key={`${item.source}-${item.type}`}>
                <span>{sourceKindLabel(item.source)} · {blockTypeLabel(item.type)}</span>
                <strong>{item.count}</strong>
              </div>
            ))}
            {fragmentSummary.length === 0 && <div className="empty-state">暂无片段记录</div>}
          </div>
        </section>

        <section className="log-panel">
          <div className="log-panel-title">
            <span><Eye size={17} /> 视觉兜底</span>
            <small>{visionRequests.length} 条</small>
          </div>
          <div className="vision-log-list">
            {visionRequests.map((request) => (
              <VisionRequestRow key={request.request_id} request={request} />
            ))}
            {visionRequests.length === 0 && <div className="empty-state">暂无视觉兜底请求</div>}
          </div>
        </section>

        <section className="log-panel log-panel-wide">
          <div className="log-panel-title">
            <span><Clock3 size={17} /> 配置快照</span>
            <small>{diagnosticsLoading ? "刷新中" : "当前病例"}</small>
          </div>
          <dl className="settings-dl log-config-dl">
            <dt>系统版本</dt>
            <dd>{activeRun?.system_config_version ?? "未知"}</dd>
            <dt>字段字典</dt>
            <dd>{activeRun?.field_dictionary_version ?? "未知"}</dd>
            <dt>OCR 默认</dt>
            <dd>{diagnostics?.config.ocr_default_profile ?? activeRun?.ocr_profile ?? "-"}</dd>
            <dt>版面默认</dt>
            <dd>{diagnostics?.config.layout_default_profile ?? activeRun?.layout_profile ?? "-"}</dd>
            <dt>LLM 默认</dt>
            <dd>{diagnostics?.config.llm_default_profile ?? activeRun?.llm_profile ?? "-"}</dd>
            <dt>视觉兜底</dt>
            <dd>{diagnostics?.config.vision_fallback_enabled ? "开启" : "关闭"} / {diagnostics?.config.vision_fallback_requires_manual_approval ? "需人工批准" : "自动"}</dd>
          </dl>
        </section>
      </div>
    </section>
  );
}

function VisionRequestRow({ request }: { request: VisionFallbackRecord }) {
  return (
    <article className="vision-log-row">
      <div>
        <strong>p.{request.page} / {request.status}</strong>
        <small>{formatTimestamp(request.created_at)}{request.approved_at ? ` / 批准 ${formatTimestamp(request.approved_at)}` : ""}</small>
      </div>
      <p>{request.reason}</p>
      <small>reviewer: {request.reviewer} / bbox {request.bbox.length ? request.bbox.join(", ") : "-"}</small>
    </article>
  );
}

function summarizeFragments(fragments: DocumentFragment[]) {
  const counts = new Map<string, { source: string; type: string; count: number }>();
  fragments.forEach((fragment) => {
    const key = `${fragment.source_kind}:${fragment.block_type}`;
    const current = counts.get(key) ?? { source: fragment.source_kind, type: fragment.block_type, count: 0 };
    current.count += 1;
    counts.set(key, current);
  });
  return Array.from(counts.values()).sort((left, right) => right.count - left.count).slice(0, 8);
}

function formatFieldKeys(keys: string[]) {
  if (keys.length === 0) return "-";
  const visible = keys.slice(0, 4).join(", ");
  return keys.length > 4 ? `${visible} +${keys.length - 4}` : visible;
}

function sourceKindLabel(value: string) {
  if (value === "intelligent_document") return "智能文档";
  if (value === "pdf_text") return "PDF文本";
  if (value === "ocr") return "OCR";
  if (value === "pp_structure") return "版面";
  if (value === "manual") return "人工";
  return value;
}

function blockTypeLabel(value: string) {
  if (value === "form_field") return "表单";
  if (value === "paragraph") return "段落";
  if (value === "title") return "标题";
  if (value === "line") return "行";
  if (value === "table") return "表格";
  return value;
}
