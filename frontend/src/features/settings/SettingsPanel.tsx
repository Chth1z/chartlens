import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
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
  getModelProfiles,
  getRuntimeSettings,
  getSystemSettings,
  updateActiveModelProfile,
  validateSettings
} from "../../shared/api/client";
import type {
  AuthStatus,
  FieldDictionarySettingsResponse,
  ModelProfilesResponse,
  RuntimeSettingsResponse,
  SettingsValidationResponse,
  SystemSettingsResponse
} from "../../shared/types/api";
import { ocrRuntimeSummary, ocrRuntimeTone } from "../diagnostics/ocrReadiness";
import { formatTimestamp } from "../../shared/utils/formatters";
import { ProviderSettingsPanel } from "./ProviderSettingsPanel";

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
  const [modelProfiles, setModelProfiles] = useState<ModelProfilesResponse | null>(null);
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
      const [systemPayload, dictionaryPayload, runtimePayload, validationPayload, modelProfilesPayload] = await Promise.all([
        getSystemSettings(),
        getFieldDictionarySettings(),
        getRuntimeSettings(),
        validateSettings(),
        getModelProfiles()
      ]);
      setSystem(systemPayload);
      setDictionary(dictionaryPayload);
      setRuntime(runtimePayload);
      setValidation(validationPayload);
      setModelProfiles(modelProfilesPayload);
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

  async function selectModelProfile(profileId: string) {
    setActionLoading("model");
    setAction(null);
    try {
      const payload = await updateActiveModelProfile(profileId);
      setModelProfiles(payload);
      setAction({
        tone: "ok",
        message: `模型 profile 已切换为 ${payload.active.label ?? payload.active.profile_id}`
      });
      await onAuthRefresh();
      await loadSettings();
    } catch (err) {
      setAction({
        tone: "error",
        message: err instanceof Error ? err.message : "模型 profile 切换失败"
      });
    } finally {
      setActionLoading(null);
    }
  }

  const systemConfig = system?.system_config;
  const dictionaryConfig = dictionary?.field_dictionary;
  const runtimeSettings = runtime?.runtime_settings;
  const activeModel = modelProfiles?.profiles.find((profile) => profile.profile_id === modelProfiles.active_profile_id);
  const activeModelRef = modelProfiles?.active_model_ref ?? activeModel?.model_ref ?? activeModel?.model ?? "-";
  const resolvedModelChain = modelProfiles?.resolved_chain?.join(" -> ") ?? activeModel?.fallbacks?.join(" -> ") ?? "无";
  const onlineModelState = auth.model_auth.online_model_available ? "在线可用" : "本地回退或未配置凭据";
  const ocrService = runtimeSettings?.services?.ocr;
  const ocrTone = ocrRuntimeTone(ocrService);
  const ocrSummary = ocrRuntimeSummary(ocrService);
  const documentEngine = ocrService
    ? ocrStatusLabel(ocrService.status, ocrService.ready)
    : systemConfig?.ocr_document_ai_configured
    ? "HTTP sidecar"
    : systemConfig?.ocr_openai_configured
      ? systemConfig.ocr_openai_model ?? "OpenAI vision"
      : "未配置";

  return (
    <section className="settings-panel">
      <div className="settings-header">
        <div>
          <h3>配置概览</h3>
          <p>核对当前抽取链路、凭据状态、字段字典和本机维护项。</p>
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

      <div className="settings-overview" aria-label="设置概览">
        <article className={`settings-overview-card ${auth.model_auth.online_model_available ? "tone-ok" : "tone-warning"}`}>
          <Bot size={18} />
          <span>抽取模型</span>
          <strong>{activeModelRef}</strong>
          <small>{onlineModelState} / {modelAvailabilityText(activeModel, modelProfiles)}</small>
        </article>
        <article className={`settings-overview-card tone-${ocrTone}`}>
          <FileCog size={18} />
          <span>智能文档</span>
          <strong>{documentEngine}</strong>
          <small>{ocrSummary}</small>
        </article>
        <article className={`settings-overview-card ${validation ? (validation.ok ? "tone-ok" : "tone-danger") : ""}`}>
          <CheckCircle2 size={18} />
          <span>配置校验</span>
          <strong>{validation ? (validation.ok ? "通过" : `${validation.validation_errors.length} 个问题`) : "读取中"}</strong>
          <small>{runtime?.restart_required_hints.length ? `需重启：${runtime.restart_required_hints.join(", ")}` : "无需重启提示"}</small>
        </article>
        <article className="settings-overview-card">
          <Database size={18} />
          <span>工作线程</span>
          <strong>{runtimeSettings ? `${runtimeSettings.case_workers}/${runtimeSettings.ocr_page_workers}/${runtimeSettings.llm_workers}` : "-"}</strong>
          <small>病例 / 文档解析 / LLM</small>
        </article>
      </div>

      <ProviderSettingsPanel onAuthRefresh={onAuthRefresh} />

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
            <dt>OCR 策略</dt>
            <dd>{systemConfig?.ocr_strategy ?? "intelligent"}</dd>
            <dt>Profile 引擎</dt>
            <dd>{systemConfig?.ocr_profile_engines?.join(" -> ") ?? "-"}</dd>
            <dt>外部文档服务</dt>
            <dd>{systemConfig?.ocr_document_ai_configured ? "已配置" : "未配置"}</dd>
            <dt>视觉模型</dt>
            <dd>{systemConfig?.ocr_openai_configured ? systemConfig?.ocr_openai_model ?? "-" : "未配置密钥"}</dd>
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

        <article className="settings-card model-route-card">
          <div className="settings-card-title">
            <Bot size={18} />
            <span>当前抽取链路</span>
          </div>
          <dl className="settings-dl">
            <dt>供应商</dt>
            <dd>{providerLabel(activeModel?.provider, activeModel?.provider_id)}</dd>
            <dt>模型引用</dt>
            <dd><code>{activeModel?.model_ref ?? "-"}</code></dd>
            <dt>模型</dt>
            <dd>{activeModel?.model ?? "-"}</dd>
            <dt>API</dt>
            <dd>{activeModel?.api ?? "-"}</dd>
            <dt>Base URL</dt>
            <dd><code>{activeModel?.base_url ?? "默认"}</code></dd>
            <dt>输出约束</dt>
            <dd>{activeModel?.response_format ?? "-"}</dd>
            <dt>凭据状态</dt>
            <dd>{modelAvailabilityText(activeModel, modelProfiles)}</dd>
            <dt>生效状态</dt>
            <dd className={auth.model_auth.online_model_available ? "text-ok" : "text-warning"}>{onlineModelState}</dd>
            <dt>回退链</dt>
            <dd>{resolvedModelChain}</dd>
          </dl>
          <details className="settings-advanced">
            <summary>高级：切换静态 profile</summary>
            <label className="settings-field compact">
              <span>静态 profile</span>
              <select
                className="settings-select"
                value={modelProfiles?.active_profile_id ?? ""}
                disabled={loading || actionLoading !== null || !modelProfiles}
                onChange={(event) => void selectModelProfile(event.target.value)}
              >
                {(modelProfiles?.profiles ?? []).map((profile) => (
                  <option key={profile.profile_id} value={profile.profile_id}>
                    {(profile.label ?? profile.profile_id)} · {profile.model_ref ?? profile.model}
                  </option>
                ))}
              </select>
            </label>
            <p>Provider 页面启用模型后会写入动态 profile。这里仅用于切换配置文件里的静态模型和回退链。</p>
          </details>
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
              病例 {runtimeSettings?.case_workers ?? "-"} / 文档解析 {runtimeSettings?.ocr_page_workers ?? "-"} / LLM {runtimeSettings?.llm_workers ?? "-"}
            </dd>
            <dt>Profile 引擎</dt>
            <dd>{runtimeSettings?.ocr_profile_engines?.join(" -> ") ?? "-"}</dd>
            <dt>文档服务</dt>
            <dd>{runtimeSettings?.ocr_document_ai_configured ? "HTTP sidecar" : runtimeSettings?.ocr_openai_configured ? runtimeSettings?.ocr_openai_model ?? "OpenAI vision" : "未配置"}</dd>
            <dt>OCR 状态</dt>
            <dd className={ocrTone === "ok" ? "text-ok" : ocrTone === "danger" ? "text-error" : "text-warning"}>{ocrSummary}</dd>
            <dt>OCR health</dt>
            <dd><code>{ocrService?.health_url ?? "-"}</code></dd>
            <dt>OCR profile</dt>
            <dd>{ocrService?.profile_id ?? runtimeSettings?.ocr_profile ?? "-"}</dd>
            <dt>重启项</dt>
            <dd>{runtime?.restart_required_hints.join(", ") ?? "-"}</dd>
          </dl>
          {!!ocrService?.checks?.length && (
            <ul className="runtime-check-list" aria-label="OCR 就绪检查">
              {ocrService.checks.map((check) => (
                <li key={check.key} className={check.ready ? "text-ok" : "text-error"}>
                  <span>{check.label}</span>
                  <strong>{check.ready ? "就绪" : "未就绪"}</strong>
                  {!check.ready && check.reason && <small>{check.reason}</small>}
                </li>
              ))}
            </ul>
          )}
          {!!ocrService?.actions?.length && (
            <div className="settings-command-list" aria-label="OCR 修复命令">
              {ocrService.actions.map((item) => (
                <div key={`${item.label}-${item.command}`}>
                  <span>{item.label}</span>
                  <code>{item.command}</code>
                </div>
              ))}
            </div>
          )}
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
            <dt>应用访问</dt>
            <dd>{auth.enabled ? (auth.session_auth.authenticated ? "已登录" : "未登录") : "本机直接访问"} / {auth.session_auth.provider}</dd>
            <dt>会话用户</dt>
            <dd>{auth.session_auth.user?.email ?? auth.session_auth.user?.name ?? auth.user?.email ?? "本地模式"}</dd>
            <dt>Cookie</dt>
            <dd><code>{auth.session_auth.cookie_name}</code></dd>
            <dt>会话过期</dt>
            <dd>{formatTimestamp(auth.session_auth.expires_at)}</dd>
            <dt>抽取通道</dt>
            <dd>{auth.model_auth.provider} / {onlineModelState}</dd>
            <dt>API Key</dt>
            <dd>{auth.model_auth.api_key_configured ? "当前模型凭据已配置" : "当前模型缺少在线凭据"}</dd>
            <dt>ChatGPT Token</dt>
            <dd>{auth.model_auth.token_cache_exists ? `已缓存：${modelIdentity}` : "未使用"}</dd>
            <dt>Token 更新</dt>
            <dd>{auth.model_auth.token_cache_exists ? formatTimestamp(auth.model_auth.updated_at) : "无"}</dd>
            <dt>Token 过期</dt>
            <dd>{auth.model_auth.token_cache_exists ? formatTimestamp(auth.model_auth.expires_at) : "无"}</dd>
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

function providerLabel(provider: string | null | undefined, providerId?: string | null) {
  if (providerId) return providerId;
  if (provider === "openai_responses") return "OpenAI Responses";
  if (provider === "openai_compatible") return "OpenAI-compatible Chat";
  if (provider === "disabled") return "本地保守 fallback";
  return provider ?? "-";
}

function ocrStatusLabel(status: string, ready: boolean | null) {
  if (ready === true || status === "ready") return "强链路已就绪";
  if (status === "not_running") return "Sidecar 未运行";
  if (status === "not_configured") return "未配置";
  if (status === "external") return "外部状态";
  return "强链路未就绪";
}

function modelAvailabilityText(profile: ModelProfilesResponse["profiles"][number] | null | undefined, payload: ModelProfilesResponse | null) {
  if (!profile || !payload) return "-";
  if (profile.profile_id === "openai_structured") return payload.env.openai_api_key_configured ? "OpenAI key 已配置" : "缺少 EYEX_OPENAI_API_KEY";
  if (profile.profile_id.startsWith("deepseek")) return payload.env.deepseek_api_key_configured ? "DeepSeek key 已配置" : "缺少 EYEX_DEEPSEEK_API_KEY";
  if (profile.auth_configured) return profile.auth_optional ? "本地/可选 key" : "API key 已配置";
  if (profile.profile_id === "openai_compatible_custom") {
    if (!profile.base_url) return "缺少 EYEX_COMPATIBLE_BASE_URL";
    if (!profile.model || profile.model === "custom-model") return "建议设置 EYEX_COMPATIBLE_MODEL";
    return payload.env.compatible_api_key_configured ? "兼容 key 已配置" : "缺少 EYEX_COMPATIBLE_API_KEY";
  }
  if (profile.profile_id === "local_disabled") return "无需在线 key";
  return "按 profile 配置读取";
}
