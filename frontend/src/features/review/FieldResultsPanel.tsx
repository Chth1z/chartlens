import { memo, useMemo, useState } from "react";
import { ChevronDown, Filter, Search } from "lucide-react";
import type { FieldDefinition, FieldResult } from "../../shared/types/api";
import { confidenceBand, type FilterMode } from "../cases/status";

interface FieldResultsPanelProps {
  filteredResults: FieldResult[];
  fieldMap: Map<string, FieldDefinition>;
  filter: FilterMode;
  query: string;
  selectedField: string;
  title?: string;
  setFilter: (filter: FilterMode) => void;
  setQuery: (query: string) => void;
  setSelectedField: (fieldKey: string) => void;
  setReviewCode: (code: string) => void;
}

export const FieldResultsPanel = memo(function FieldResultsPanel({
  filteredResults,
  fieldMap,
  filter,
  query,
  selectedField,
  title = "字段结果",
  setFilter,
  setQuery,
  setSelectedField,
  setReviewCode
}: FieldResultsPanelProps) {
  const [filterOpen, setFilterOpen] = useState(false);
  const filterOptions: Array<[FilterMode, string]> = [
    ["all", "全部"],
    ["model_failed", "模型失败"],
    ["ocr_low", "OCR低质"],
    ["no_evidence", "无证据"],
    ["review", "需复核"],
    ["manual_review", "人工复核"],
    ["accepted", "已确认"]
  ];
  const activeFilterLabel = filterOptions.find(([key]) => key === filter)?.[1] ?? "全部";
  const sortedResults = useMemo(() => [...filteredResults].sort(compareFieldRisk), [filteredResults]);

  return (
    <section className="fields-panel">
      <div className="panel-title">
        <span>{title}</span>
        <small>{filteredResults.length} 项</small>
      </div>
      <div className="field-toolbar">
        <label className="search-box">
          <Search size={16} />
          <input
            aria-label="搜索字段或证据"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索字段或证据"
          />
        </label>
        <div className="field-filter">
          <button
            aria-expanded={filterOpen}
            aria-haspopup="menu"
            className="field-filter-trigger"
            onClick={() => setFilterOpen((open) => !open)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setFilterOpen(false);
            }}
            type="button"
          >
            <Filter size={15} />
            <span>{activeFilterLabel}</span>
            <ChevronDown size={15} aria-hidden="true" />
          </button>
          {filterOpen && (
            <div className="field-filter-menu" role="menu" aria-label="字段筛选">
              {filterOptions.map(([key, label]) => (
                <button
                  aria-checked={filter === key}
                  className={filter === key ? "active" : ""}
                  key={key}
                  onClick={() => {
                    setFilter(key);
                    setFilterOpen(false);
                  }}
                  role="menuitemradio"
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="field-table-header field-row header" aria-hidden="true">
        <span>字段</span>
        <span>编码</span>
        <span>置信度</span>
        <span>状态</span>
      </div>
      <div className="field-table" role="list">
        {filteredResults.length === 0 && <div className="empty-state">暂无字段结果</div>}
        {sortedResults.map((result) => {
          const field = fieldMap.get(result.field_key);
          const band = confidenceBand(result);
          const statusText = riskStatusText(result, band);
          return (
            <button
              className={`field-row ${selectedField === result.field_key ? "selected" : ""}`}
              key={result.field_key}
              aria-current={selectedField === result.field_key ? "true" : undefined}
              aria-label={`${field?.label ?? result.field_key}，编码 ${result.normalized_code ?? "unknown"}，置信度 ${Math.round(result.confidence * 100)}%，${statusText}`}
              onClick={() => {
                setSelectedField(result.field_key);
                setReviewCode(result.normalized_code ?? "unknown");
              }}
              role="listitem"
              type="button"
            >
              <span>
                <strong>{field?.label ?? result.field_key}</strong>
                <small>{field?.export_header ?? result.field_key}</small>
              </span>
              <span>{result.normalized_code ?? "unknown"}</span>
              <span className="confidence-cell">
                <i className="confidence-bar" style={{ width: `${Math.max(6, result.confidence * 100)}%` }} />
                {Math.round(result.confidence * 100)}%
              </span>
              <span className={`badge ${band}`}>{statusText}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
});

function compareFieldRisk(left: FieldResult, right: FieldResult) {
  const score = (result: FieldResult) => {
    if (result.validation_state === "rejected") return 500;
    if (result.risk_level === "critical") return 450;
    if (result.review_required) return 400;
    if (result.error_code) return 350;
    if (result.risk_level === "high") return 300;
    if ((result.normalized_code ?? "unknown") === "unknown") return 200;
    if (result.risk_level === "medium") return 100;
    return 0;
  };
  return score(right) - score(left) || left.field_key.localeCompare(right.field_key);
}

function riskStatusText(result: FieldResult, band: ReturnType<typeof confidenceBand>) {
  if (band === "manual_review" || result.validation_state === "reviewed" || result.acceptance_reason === "manual_review") return "人工复核";
  const decisionStatus = typeof result.provenance?.decision_status === "string" ? result.provenance.decision_status : null;
  if (decisionStatus === "CONFLICT") return "冲突";
  if (decisionStatus === "MISSING") return "无证据";
  if (decisionStatus === "REVIEW") return "需复核";
  if (result.validation_state === "rejected") return "已拦截";
  if (result.error_code === "NO_EVIDENCE_CANDIDATES_SKIPPED_LLM") return "无证据";
  if (result.error_code === "DEIDENTIFICATION_RISK_BLOCKED_ONLINE_LLM") return "脱敏复核";
  if (result.error_code === "LLM_PROVIDER_FAILED") return "模型失败";
  if (result.error_code === "LOW_OCR_CONFIDENCE") return "OCR低质";
  if (result.error_code === "COMPLEX_FIELD_REQUIRES_FACTS") return "需事实";
  if (band === "accepted") return "自动填入";
  if (band === "review") return "需复核";
  return "不详";
}
