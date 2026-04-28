import { CheckCircle2, History } from "lucide-react";
import type { CaseRecord, FieldDefinition, FieldResult } from "../../shared/types/api";

interface ReviewPanelProps {
  selectedCase?: CaseRecord;
  activeResult?: FieldResult;
  fieldMap: Map<string, FieldDefinition>;
  reviewCode: string;
  reviewReason: string;
  loading: boolean;
  setReviewCode: (code: string) => void;
  setReviewReason: (reason: string) => void;
  submitReview: () => void | Promise<void>;
}

export function ReviewPanel({
  selectedCase,
  activeResult,
  fieldMap,
  reviewCode,
  reviewReason,
  loading,
  setReviewCode,
  setReviewReason,
  submitReview
}: ReviewPanelProps) {
  const activeField = activeResult ? fieldMap.get(activeResult.field_key) : undefined;
  const codeOptions = activeField?.allowed_codes.filter((code) => !["integer", "text"].includes(code)) ?? [];
  const useCodeOptions = codeOptions.length > 0 && (activeField?.type === "enum" || codeOptions.length > 1);
  const codeInputId = activeResult ? `review-code-${activeResult.field_key}` : "review-code";
  const reasonInputId = activeResult ? `review-reason-${activeResult.field_key}` : "review-reason";

  return (
    <aside className="audit-panel">
      <div className="panel-title">
        <span>复核与审计</span>
        <small><History size={14} /> {selectedCase?.audit_count ?? 0} 次修改</small>
      </div>
      {activeResult ? (
        <div className="review-card">
          <h3>{activeField?.label ?? activeResult.field_key}</h3>
          <dl>
            <dt>当前值</dt>
            <dd>{activeResult.raw_value ?? "不详"} / {activeResult.normalized_code ?? "unknown"}</dd>
            <dt>导出列</dt>
            <dd>{activeField?.export_header ?? activeResult.field_key}</dd>
            <dt>证据</dt>
            <dd>{activeResult.evidence_text ?? "未找到证据"}</dd>
            <dt>模型说明</dt>
            <dd>{activeResult.reasoning_summary ?? "无"}</dd>
          </dl>
          <div className="review-control">
            <span className="review-label" id={`${codeInputId}-label`}>复核编码</span>
            {useCodeOptions ? (
              <div className="review-code-options" role="radiogroup" aria-labelledby={`${codeInputId}-label`}>
                {codeOptions.map((code) => (
                  <button
                    aria-checked={reviewCode === code}
                    className={reviewCode === code ? "active" : ""}
                    key={code}
                    onClick={() => setReviewCode(code)}
                    role="radio"
                    type="button"
                  >
                    {formatCodeLabel(code)}
                  </button>
                ))}
              </div>
            ) : (
              <input
                id={codeInputId}
                value={reviewCode}
                onChange={(event) => setReviewCode(event.target.value)}
                aria-labelledby={`${codeInputId}-label`}
              />
            )}
          </div>
          <label htmlFor={reasonInputId}>
            修改原因
            <textarea id={reasonInputId} value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} />
          </label>
          <button className="icon-button primary full" onClick={() => void submitReview()} disabled={loading} type="button">
            <CheckCircle2 size={16} /> 确认复核
          </button>
        </div>
      ) : (
        <div className="empty-state">没有可复核字段</div>
      )}
    </aside>
  );
}

function formatCodeLabel(code: string) {
  if (code === "unknown") return "不详";
  return code;
}
