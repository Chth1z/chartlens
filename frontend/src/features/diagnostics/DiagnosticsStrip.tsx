import { memo } from "react";
import { AlertTriangle, BrainCircuit, Clock3, FileSearch, Layers, RefreshCw } from "lucide-react";
import type { CaseDiagnostics, CaseRecord, OcrQuality, ProcessingRun, RuntimeServiceStatus } from "../../shared/types/api";
import { formatMs, isWorkingStatus, qualityText, statusLabel } from "../cases/status";
import { formatTokenSummary } from "./diagnosticsLog";
import { formatOcrProcessingError, ocrReadinessSummary, ocrRuntimeSummary } from "./ocrReadiness";

interface DiagnosticsStripProps {
  selectedCase?: CaseRecord;
  activeQuality?: OcrQuality;
  activeRun: ProcessingRun | null;
  diagnostics: CaseDiagnostics | null;
  diagnosticsLoading: boolean;
  cacheHit: boolean;
  cachedInputTokens: number;
  latestModelLabel: string;
  ocrRuntimeService?: RuntimeServiceStatus | null;
}

export const DiagnosticsStrip = memo(function DiagnosticsStrip({
  selectedCase,
  activeQuality,
  activeRun,
  diagnostics,
  diagnosticsLoading,
  cacheHit,
  cachedInputTokens,
  latestModelLabel,
  ocrRuntimeService
}: DiagnosticsStripProps) {
  const pageCacheHits = metricNumber(activeRun, "page_cache_hit_count");
  const secondPassPages = metricNumberArray(activeRun, "second_pass_ocr_pages");
  const skippedNoEvidence = metricNumber(activeRun, "llm_skipped_no_evidence_count");
  const llmCalls = metricNumber(activeRun, "llm_call_count");
  const layoutProvider = metricString(activeRun, "layout_provider") || activeRun?.layout_profile || "chinese_inpatient_v1";
  const layoutRegions = metricNumber(activeRun, "layout_region_count");
  const layoutCacheHits = metricNumber(activeRun, "layout_cache_hit_count");
  const lowConfidenceSections = metricNumber(activeRun, "low_confidence_section_count");
  const ocrEngine = activeQuality?.ocr_engine || metricString(activeRun, "ocr_engine") || "none";
  const ocrStatus = activeQuality?.ocr_intelligent_status || metricString(activeRun, "ocr_intelligent_status") || (selectedCase?.status === "failed" ? "failed" : "pending");
  const unavailableEngines = activeQuality?.ocr_unavailable_engines ?? [];
  const attemptedEngines = activeQuality?.ocr_attempted_engines ?? [];
  const unavailableReasons = activeQuality?.ocr_unavailable_reasons ?? metricStringRecord(activeRun, "ocr_unavailable_reasons");
  const ocrEngineErrors = activeQuality?.ocr_engine_errors ?? metricStringRecord(activeRun, "ocr_engine_errors");
  const ocrTraceError = metricString(activeRun, "ocr_trace_error");
  const ocrSelectedEngine = metricString(activeRun, "ocr_selected_engine") || ocrEngine;
  const ocrReady = ocrStatus === "completed";
  const runtimeOcrSummary = ocrRuntimeService?.ready === false ? ocrRuntimeSummary(ocrRuntimeService) : null;
  const processingError = formatOcrProcessingError(activeRun?.error_message || selectedCase?.error_message, unavailableReasons, ocrEngineErrors, ocrTraceError);
  const tokenSummary = formatTokenSummary(activeRun?.input_tokens, cachedInputTokens, activeRun?.output_tokens);
  const extractMs = metricNumber(activeRun, "extract_ms");
  const persistMs = metricNumber(activeRun, "persist_ms");
  const ocrTraceTotalMs = metricNumber(activeRun, "ocr_trace_total_ms");
  const ocrSlowestStage = metricString(activeRun, "ocr_slowest_stage");
  const ocrSlowestStageMs = metricNumber(activeRun, "ocr_slowest_stage_ms");
  const ocrTimedOutStages = metricNumber(activeRun, "ocr_timed_out_stage_count");
  const ocrFailedStages = metricNumber(activeRun, "ocr_failed_stage_count");

  return (
    <section className="diagnostics-strip" aria-label="处理摘要">
      <div className="processing-summary">
        <div className={`summary-card summary-status status-${selectedCase?.status ?? "queued"}`}>
          <span><RefreshCw size={15} /> 处理状态</span>
          <strong>{selectedCase ? statusLabel(selectedCase.status) : "未选择"}</strong>
          <small>{processingError ?? (selectedCase && isWorkingStatus(selectedCase.status) ? "后台处理中" : "任务已结束")}</small>
        </div>
        <div className={`summary-card summary-ocr quality-${ocrReady ? activeQuality?.quality_band ?? "poor" : "poor"}`}>
          <span>{ocrReady ? <BrainCircuit size={15} /> : <AlertTriangle size={15} />} 智能文档</span>
          <strong>{ocrReady ? ocrEngine : ocrSelectedEngine && ocrSelectedEngine !== "none" ? ocrSelectedEngine : "引擎未就绪"}</strong>
          <small>
            {ocrReady
              ? `${qualityText(activeQuality?.quality_band)} / ${activeQuality?.ocr_block_count ?? 0} 块${cacheHit ? " / 缓存命中" : ""}`
              : runtimeOcrSummary ?? processingError ?? ocrReadinessSummary(attemptedEngines, unavailableEngines, unavailableReasons, ocrEngineErrors, ocrTraceError)}
          </small>
        </div>
        <div className="summary-card summary-layout">
          <span><Layers size={15} /> 版面</span>
          <strong>{layoutProvider}</strong>
          <small>{diagnosticsLoading ? "刷新中" : `${diagnostics?.fragments.length ?? 0} 段 / ${layoutRegions} 区域`}{layoutCacheHits ? ` / 缓存 ${layoutCacheHits}` : ""}{lowConfidenceSections ? ` / 低置信 ${lowConfidenceSections}` : ""}{unavailableEngines.length ? ` / 缺 ${unavailableEngines.join(",")}` : ""}</small>
        </div>
        <div className="summary-card summary-time">
          <span><Clock3 size={15} /> 耗时</span>
          <strong>{formatMs(activeRun?.latency_ms)}</strong>
          <small>
            OCR {formatMs(metricNumber(activeRun, "ocr_ms"))}
            {ocrTraceTotalMs ? ` / 链路 ${formatMs(ocrTraceTotalMs)}` : ""}
            {" / "}版面 {formatMs(metricNumber(activeRun, "layout_ms"))}
            {" / "}抽取 {formatMs(extractMs)}
            {" / "}保存 {formatMs(persistMs)}
            {ocrSlowestStageMs ? ` / 最慢 ${ocrSlowestStage || "OCR阶段"} ${formatMs(ocrSlowestStageMs)}` : ""}
            {pageCacheHits ? ` / 页缓存 ${pageCacheHits}` : ""}
            {secondPassPages.length ? ` / 二次 p.${secondPassPages.join(",")}` : ""}
            {ocrTimedOutStages ? ` / 超时 ${ocrTimedOutStages}` : ""}
            {ocrFailedStages ? ` / 失败阶段 ${ocrFailedStages}` : ""}
            {Object.keys(ocrEngineErrors).length ? " / 有错误" : ""}
          </small>
        </div>
        <div className="summary-card summary-model">
          <span><FileSearch size={15} /> 模型</span>
          <strong>{diagnostics?.model_calls.length ?? 0} 条</strong>
          <small>{latestModelLabel} / 调用 {llmCalls} / 跳过 {skippedNoEvidence} / tokens {tokenSummary}</small>
        </div>
      </div>
    </section>
  );
});

function metricNumber(run: ProcessingRun | null, key: string): number {
  const value = run?.step_timings?.[key];
  return typeof value === "number" ? value : 0;
}

function metricNumberArray(run: ProcessingRun | null, key: string): number[] {
  const value = run?.step_timings?.[key];
  return Array.isArray(value) ? value.filter((item): item is number => typeof item === "number") : [];
}

function metricString(run: ProcessingRun | null, key: string): string {
  const value = run?.step_timings?.[key];
  return typeof value === "string" ? value : "";
}

function metricStringRecord(run: ProcessingRun | null, key: string): Record<string, string> {
  const value = run?.step_timings?.[key];
  if (!value || Array.isArray(value) || typeof value !== "object") return {};
  return Object.fromEntries(
    Object.entries(value)
      .filter((entry): entry is [string, string] => typeof entry[1] === "string")
  );
}
