import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileCog,
  KeyRound,
  RefreshCw,
  ShieldCheck,
  Trash2,
  XCircle
} from "lucide-react";
import {
  clearAllCases,
  clearProcessingCache,
  deleteModelToken,
  getFieldDictionarySettings,
  getRuntimeSettings,
  getSystemSettings,
  validateSettings
} from "../../shared/api/client";
import type {
  AuthStatus,
  FieldDictionarySettingsResponse,
  RuntimeSettingsResponse,
  SettingsValidationResponse,
  SystemSettingsResponse
} from "../../shared/types/api";

interface SettingsPanelProps {
  auth: AuthStatus;
  onAuthRefresh: () => Promise<void> | void;
  onCasesCleared: () => void;
}

type ActionState = {
  tone: "ok" | "error";
  message: string;
};

export function SettingsPanel({ auth, onAuthRefresh, onCasesCleared }: SettingsPanelProps) {
  const [system, setSystem] = useState<SystemSettingsResponse | null>(null);
  const [dictionary, setDictionary] = useState<FieldDictionarySettingsResponse | null>(null);
  const [runtime, setRuntime] = useState<RuntimeSettingsResponse | null>(null);
  const [validation, setValidation] = useState<SettingsValidationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<ActionState | null>(null);

  useEffect(() => {
    void loadSettings();
  }, []);

  const modelIdentity = useMemo(() => {
    return auth.model_auth.user?.email ?? auth.model_auth.user?.name ?? auth.model_auth.provider;
  }, [auth.model_auth.provider, auth.model_auth.user]);

  async function loadSettings() {
    setLoading(true);
    setError(null);
    try {
      const [systemPayload, dictionaryPayload, runtimePayload, validationPayload] = await Promise.all([
        getSystemSettings(),
        getFieldDictionarySettings(),
        getRuntimeSettings(),
        validateSettings()
      ]);
      setSystem(systemPayload);
      setDictionary(dictionaryPayload);
      setRuntime(runtimePayload);
      setValidation(validationPayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "设置读取失败");
    } finally {
      setLoading(false);
    }
  }

  async function runAction(
    key: string,
    confirmMessage: string,
    actionFn: () => Promise<{ message?: string; affected_count?: number }>,
    after?: () => Promise<void> | void
  ) {
    if (!window.confirm(confirmMessage)) return;
    setActionLoading(key);
    setAction(null);
    try {
      const result = await actionFn();
      await after?.();
      setAction({
        tone: "ok",
        message: result.message ?? `已处理 ${result.affected_count ?? 0} 项`
      });
      await loadSettings();
    } catch (err) {
      setAction({
        tone: "error",
        message: err instanceof Error ? err.message : "操作失败"
      });
    } finally {
      setActionLoading(null);
    }
  }

  const systemConfig = system?.system_config;
  const dictionaryConfig = dictionary?.field_dictionary;
  const runtimeSettings = runtime?.runtime_settings;

  return (
    <section className="settings-panel">
      <div className="settings-header">
        <div>
          <h3>设置</h3>
          <p>单机运行配置、字段字典、账号凭据与本地维护。</p>
        </div>
        <button className="icon-button" onClick={() => void loadSettings()} disabled={loading} type="button">
          <RefreshCw size={16} className={loading ? "spin" : ""} /> 刷新
        </button>
      </div>

      {error && <div className="error-banner"><AlertTriangle size={16} /> {error}</div>}
      {action && (
        <div className={`settings-message ${action.tone}`}>
          {action.tone === "ok" ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          {action.message}
        </div>
      )}

      <div className="settings-grid">
        <article className="settings-card">
          <div className="settings-card-title">
            <FileCog size={18} />
            <span>系统设置</span>
          </div>
          <dl className="settings-dl">
            <dt>配置文件</dt>
            <dd><code>{systemConfig?.path ?? "读取中"}</code></dd>
            <dt>版本</dt>
            <dd>{systemConfig?.version ?? "-"}</dd>
            <dt>OCR 默认</dt>
            <dd>{systemConfig?.ocr_default_profile ?? "-"}</dd>
            <dt>版面规则</dt>
            <dd>{systemConfig?.layout_default_profile ?? "-"}</dd>
            <dt>LLM profile</dt>
            <dd>{systemConfig?.llm_default_profile ?? "-"}</dd>
          </dl>
          <div className="settings-tags">
            {(systemConfig?.ocr_profiles ?? []).map((item) => <span key={`ocr-${item}`}>OCR {item}</span>)}
            {(systemConfig?.layout_profiles ?? []).map((item) => <span key={`layout-${item}`}>Layout {item}</span>)}
            {(systemConfig?.llm_profiles ?? []).map((item) => <span key={`llm-${item}`}>LLM {item}</span>)}
          </div>
        </article>

        <article className="settings-card">
          <div className="settings-card-title">
            <Database size={18} />
            <span>运行环境</span>
          </div>
          <dl className="settings-dl">
            <dt>SQLite</dt>
            <dd><code>{runtimeSettings?.database_url ?? "读取中"}</code></dd>
            <dt>存储目录</dt>
            <dd><code>{runtimeSettings?.storage_dir ?? "-"}</code></dd>
            <dt>同步处理</dt>
            <dd>{runtimeSettings?.sync_pipeline ? "开启" : "关闭"}</dd>
            <dt>工作线程</dt>
            <dd>
              病例 {runtimeSettings?.case_workers ?? "-"} / OCR {runtimeSettings?.ocr_page_workers ?? "-"} / LLM {runtimeSettings?.llm_workers ?? "-"}
            </dd>
            <dt>重启项</dt>
            <dd>{runtime?.restart_required_hints.join(", ") ?? "-"}</dd>
          </dl>
        </article>

        <article className="settings-card">
          <div className="settings-card-title">
            <FileCog size={18} />
            <span>字段字典</span>
          </div>
          <dl className="settings-dl">
            <dt>字典文件</dt>
            <dd><code>{dictionaryConfig?.path ?? "读取中"}</code></dd>
            <dt>版本</dt>
            <dd>{dictionaryConfig?.version ?? "-"}</dd>
            <dt>字段数</dt>
            <dd>{dictionaryConfig ? `${dictionaryConfig.field_count} 个，首期 ${dictionaryConfig.phase_1_count} 个` : "-"}</dd>
            <dt>校验</dt>
            <dd className={validation?.ok ? "text-ok" : "text-error"}>
              {validation ? (validation.ok ? "通过" : `${validation.validation_errors.length} 个问题`) : "读取中"}
            </dd>
          </dl>
          {validation && !validation.ok && (
            <ul className="settings-errors">
              {validation.validation_errors.map((item) => <li key={item}>{item}</li>)}
            </ul>
          )}
          <div className="settings-tags">
            {(dictionaryConfig?.fields.slice(0, 12) ?? []).map((field) => <span key={field.key}>{field.label}</span>)}
          </div>
        </article>

        <article className="settings-card">
          <div className="settings-card-title">
            <ShieldCheck size={18} />
            <span>账号与凭据</span>
          </div>
          <dl className="settings-dl">
            <dt>应用会话</dt>
            <dd>{auth.session_auth.authenticated ? "有效" : "无效"} / {auth.session_auth.provider}</dd>
            <dt>会话用户</dt>
            <dd>{auth.session_auth.user?.email ?? auth.session_auth.user?.name ?? auth.user?.email ?? "本地模式"}</dd>
            <dt>Cookie</dt>
            <dd><code>{auth.session_auth.cookie_name}</code></dd>
            <dt>会话过期</dt>
            <dd>{formatTimestamp(auth.session_auth.expires_at)}</dd>
            <dt>模型通道</dt>
            <dd>{auth.model_auth.provider} / {auth.model_auth.online_model_available ? "在线可用" : "本地 fallback"}</dd>
            <dt>Token 文件</dt>
            <dd>{auth.model_auth.token_cache_exists ? "存在" : "不存在"}</dd>
            <dt>Token 路径</dt>
            <dd><code>{auth.model_auth.token_cache_path}</code></dd>
            <dt>Token 用户</dt>
            <dd>{modelIdentity}</dd>
            <dt>Token 更新</dt>
            <dd>{formatTimestamp(auth.model_auth.updated_at)}</dd>
            <dt>Token 过期</dt>
            <dd>{formatTimestamp(auth.model_auth.expires_at)}</dd>
          </dl>
        </article>

        <article className="settings-card maintenance-card">
          <div className="settings-card-title">
            <Trash2 size={18} />
            <span>本地数据清理</span>
          </div>
          <div className="maintenance-actions">
            <button
              className="icon-button"
              disabled={actionLoading !== null}
              type="button"
              onClick={() =>
                void runAction(
                  "cache",
                  "清空 OCR/片段缓存？上传原文件和 SQLite 病例记录不会被删除。",
                  clearProcessingCache
                )
              }
            >
              <RefreshCw size={16} /> {actionLoading === "cache" ? "清理中" : "清空缓存"}
            </button>
            <button
              className="icon-button"
              disabled={actionLoading !== null}
              type="button"
              onClick={() =>
                void runAction(
                  "token",
                  "删除本地 ChatGPT/Codex 模型 token？浏览器应用会话 cookie 会保留。",
                  deleteModelToken,
                  onAuthRefresh
                )
              }
            >
              <KeyRound size={16} /> {actionLoading === "token" ? "删除中" : "删除模型 token"}
            </button>
            <button
              className="icon-button danger"
              disabled={actionLoading !== null}
              type="button"
              onClick={() =>
                void runAction(
                  "cases",
                  "清空全部病例数据？配置文件和模型 token 不会被删除。",
                  clearAllCases,
                  onCasesCleared
                )
              }
            >
              <XCircle size={16} /> {actionLoading === "cases" ? "清理中" : "清空全部病例"}
            </button>
          </div>
        </article>
      </div>
    </section>
  );
}

function formatTimestamp(value: number | string | null | undefined) {
  if (!value) return "无";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}
