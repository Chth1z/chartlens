import { RefreshCw } from "lucide-react";

export function SettingsPanelFallback() {
  return (
    <section className="settings-panel" aria-label="设置加载中">
      <div className="settings-card settings-loading">
        <RefreshCw size={16} className="spin" />
        <span>设置加载中...</span>
      </div>
    </section>
  );
}

export function CaseDetailLoading({ caseId }: { caseId: string }) {
  return (
    <div className="case-detail-loading" role="status" aria-live="polite">
      <RefreshCw size={18} className="spin" />
      <strong>正在载入病例详情</strong>
      <span>{caseId}</span>
    </div>
  );
}
