import { Filter, Search } from "lucide-react";
import type { FieldDefinition, FieldResult } from "../../shared/types/api";
import { confidenceBand, type FilterMode } from "../cases/status";

interface FieldResultsPanelProps {
  filteredResults: FieldResult[];
  fieldMap: Map<string, FieldDefinition>;
  filter: FilterMode;
  query: string;
  selectedField: string;
  setFilter: (filter: FilterMode) => void;
  setQuery: (query: string) => void;
  setSelectedField: (fieldKey: string) => void;
  setReviewCode: (code: string) => void;
}

export function FieldResultsPanel({
  filteredResults,
  fieldMap,
  filter,
  query,
  selectedField,
  setFilter,
  setQuery,
  setSelectedField,
  setReviewCode
}: FieldResultsPanelProps) {
  return (
    <section className="fields-panel">
      <div className="panel-title">
        <span>字段结果</span>
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
        <div className="filter-tabs" aria-label="字段筛选">
          {[
            ["all", "全部"],
            ["review", "需复核"],
            ["unknown", "缺失"],
            ["accepted", "已确认"]
          ].map(([key, label]) => (
            <button
              aria-pressed={filter === key}
              className={filter === key ? "active" : ""}
              key={key}
              onClick={() => setFilter(key as FilterMode)}
              type="button"
            >
              {key === "all" && <Filter size={14} />}
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="field-table" role="list">
        <div className="field-row header" aria-hidden="true">
          <span>字段</span>
          <span>编码</span>
          <span>置信度</span>
          <span>状态</span>
        </div>
        {filteredResults.length === 0 && <div className="empty-state">暂无字段结果</div>}
        {filteredResults.map((result) => {
          const field = fieldMap.get(result.field_key);
          const band = confidenceBand(result);
          const statusText = band === "accepted" ? "自动填入" : band === "review" ? "需复核" : "不详";
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
}
