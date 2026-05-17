import { memo } from "react";
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

export const ReviewPanel = memo(function ReviewPanel({
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
  const quickCodeOptions = codeOptions.length > 0 && codeOptions.every((code) => ["0", "1", "2", "unknown"].includes(code))
    ? codeOptions
    : [];
  const codeInputId = activeResult ? `review-code-${activeResult.field_key}` : "review-code";
  const reasonInputId = activeResult ? `review-reason-${activeResult.field_key}` : "review-reason";
  const activeDecisionStatus = activeResult ? decisionStatusLabel(activeResult) : "未生成";
  const activeReviewReasons = activeResult ? decisionReasons(activeResult) : [];
  const activeQualityStatus = activeResult ? qualityStatusLabel(activeResult) : "unknown";
  const activeAcceptanceReason = activeResult ? acceptanceReasonLabel(activeResult.acceptance_reason) : "未标注";
  const candidateEvidence = activeResult?.evidence_candidates ?? [];

  return (
    <aside className="audit-panel">
      <div className="panel-title">
        <span>复核与审计</span>
        <small><History size={14} /> {selectedCase?.audit_count ?? 0} 次修改</small>
      </div>
      {activeResult ? (
        <div className="review-card">
          <div className="review-body">
            <h3>{activeField?.label ?? activeResult.field_key}</h3>
            <dl>
              <dt>当前值</dt>
              <dd>{activeResult.raw_value ?? "不详"} / {activeResult.normalized_code ?? "unknown"}</dd>
              <dt>导出列</dt>
              <dd>{activeField?.export_header ?? activeResult.field_key}</dd>
              <dt>证据</dt>
              <dd>{activeResult.evidence_span ?? activeResult.evidence_text ?? "未找到证据"}</dd>
              <dt>证据类型</dt>
              <dd>{activeResult.evidence_type ?? "未标注"}</dd>
              <dt>字段决策</dt>
              <dd>{activeDecisionStatus}</dd>
              <dt>决策原因</dt>
              <dd>{activeReviewReasons.length > 0 ? activeReviewReasons.join("；") : activeResult.acceptance_reason ?? "未标注"}</dd>
              <dt>证据包</dt>
              <dd>{activeResult.evidence_packs?.[0]?.pack_hash ?? activeResult.evidence_candidates?.[0]?.pack_hash ?? "未生成"}</dd>
              <dt>Token</dt>
              <dd>{activeResult.evidence_packs?.[0]?.token_estimate ?? activeResult.evidence_candidates?.[0]?.token_estimate ?? 0}</dd>
              <dt>质量状态</dt>
              <dd>{activeQualityStatus} / {activeResult.risk_level ?? "medium"}</dd>
              <dt>接受原因</dt>
              <dd>{activeAcceptanceReason}</dd>
              <dt>模型说明</dt>
              <dd>{activeResult.reasoning_summary ?? "无"}</dd>
              {activeResult.validator_messages && activeResult.validator_messages.length > 0 && (
                <>
                  <dt>校验提示</dt>
                  <dd>{activeResult.validator_messages.join("；")}</dd>
                </>
              )}
            </dl>
            {candidateEvidence.length > 0 && (
              <div className="candidate-evidence-list" aria-label="候选证据">
                <strong>候选证据</strong>
                {candidateEvidence.slice(0, 4).map((candidate, index) => (
                  <div className="candidate-evidence-item" key={`${candidate.block_id}-${index}`}>
                    <span>{candidate.normalized_code ?? "unknown"} · {candidate.source_type ?? "ocr_text"} · 第 {candidate.page} 页</span>
                    <p>{candidate.evidence_text ?? candidate.text}</p>
                    {candidate.forbidden_inference_flags && candidate.forbidden_inference_flags.length > 0 && (
                      <em>已拦截：{candidate.forbidden_inference_flags.join("、")}</em>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="review-actions">
            <div className="review-control">
              <label className="review-label" htmlFor={codeInputId}>复核编码</label>
              <input
                id={codeInputId}
                value={reviewCode}
                onChange={(event) => setReviewCode(event.target.value)}
                autoComplete="off"
              />
              {quickCodeOptions.length > 0 && (
                <div className="review-code-options" aria-label="复核编码快捷选择">
                  {quickCodeOptions.map((code) => (
                    <button
                      aria-pressed={reviewCode === code}
                      className={reviewCode === code ? "active" : ""}
                      key={code}
                      onClick={() => setReviewCode(code)}
                      type="button"
                    >
                      {formatCodeLabel(code)}
                    </button>
                  ))}
                </div>
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
        </div>
      ) : (
        <div className="empty-state">没有可复核字段</div>
      )}
    </aside>
  );
});

function formatCodeLabel(code: string) {
  if (code === "unknown") return "不详";
  return code;
}

function decisionStatusLabel(result: FieldResult) {
  if (result.validation_state === "reviewed" || result.acceptance_reason === "manual_review") return "人工复核 / 已确认";
  const status = typeof result.provenance?.decision_status === "string" ? result.provenance.decision_status : null;
  if (status === "PASS") return "PASS / 证据明确";
  if (status === "REVIEW") return "REVIEW / 需复核";
  if (status === "CONFLICT") return "CONFLICT / 冲突";
  if (status === "MISSING") return "MISSING / 未找到";
  return result.validation_state ?? "未生成";
}

function qualityStatusLabel(result: FieldResult) {
  if (result.validation_state === "reviewed" || result.acceptance_reason === "manual_review") return "人工复核";
  return result.validation_state ?? "unknown";
}

function acceptanceReasonLabel(reason: string | null | undefined) {
  if (reason === "manual_review") return "人工复核确认";
  return reason ?? "未标注";
}

function decisionReasons(result: FieldResult) {
  const value = result.provenance?.review_reasons;
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}
