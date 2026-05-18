import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Plus,
  RefreshCw,
  Search
} from "lucide-react";
import {
  activateProviderModel,
  fetchProviderModels,
  getModelProviders,
  updateModelProvider
} from "../../shared/api/client";
import type { ModelProvidersResponse, ProviderModel } from "../../shared/types/api";
import {
  MODEL_SOURCE_ORDER,
  apiTypeLabel,
  connectionStatusText,
  credentialStatusText,
  formatProviderTime,
  groupModelsBySource,
  modelCountText,
  modelForUpdate,
  modelOptionsHelp,
  modelSettingsPayload,
  modelSource,
  modelSourceBadge,
  modelSourceHelp,
  modelSourceLabel,
  providerApiOptions,
  providerBlockingText,
  providerHasBaseUrl,
  providerHasCredential,
  providerIcon,
  providerIsRunnable,
  providerOptionSchema,
  providerStatusText,
  providerTone,
  reasoningEffortLabel
} from "./providerHelpers";
import type { DraftState } from "./providerHelpers";

interface ProviderSettingsPanelProps {
  onAuthRefresh: () => Promise<void> | void;
}

export function ProviderSettingsPanel({ onAuthRefresh }: ProviderSettingsPanelProps) {
  const [payload, setPayload] = useState<ModelProvidersResponse | null>(null);
  const [selectedProviderId, setSelectedProviderId] = useState("openai");
  const [draft, setDraft] = useState<DraftState>({
    enabled: true,
    api: "openai-responses",
    apiKey: "",
    baseUrl: "",
    selectedModel: "",
    reasoningEffort: "low",
    temperature: "0",
    maxOutputTokens: "4096"
  });
  const [query, setQuery] = useState("");
  const [modelQuery, setModelQuery] = useState("");
  const [manualModelId, setManualModelId] = useState("");
  const [manualModelName, setManualModelName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    void loadProviders();
  }, []);

  const providers = payload?.providers ?? [];
  const filteredProviders = providers.filter((provider) => {
    const text = `${provider.label} ${provider.provider_id} ${provider.description}`.toLowerCase();
    return !query || text.includes(query.toLowerCase());
  });
  const selected = providers.find((provider) => provider.provider_id === selectedProviderId) ?? providers[0];
  const activeProvider = providers.find((provider) => provider.active) ?? selected;
  const runnableProviderCount = providers.filter(providerIsRunnable).length;
  const verifiedProviderCount = providers.filter((provider) => provider.connection_status === "verified").length;
  const activeModelRef = payload?.active.model_ref ?? (activeProvider?.selected_model ? `${activeProvider.provider_id}/${activeProvider.selected_model}` : "-");
  const canFetchSelected = Boolean(selected && providerHasCredential(selected, draft) && providerHasBaseUrl(selected, draft));
  const canActivateSelected = Boolean(selected && draft.enabled && providerHasCredential(selected, draft) && providerHasBaseUrl(selected, draft));
  const optionSchema = selected ? providerOptionSchema(selected, draft.api) : undefined;
  const models = useMemo(() => {
    const list = selected?.models ?? [];
    return list.filter((model) => {
      const text = `${model.id} ${model.name ?? ""} ${model.source ?? ""}`.toLowerCase();
      return !modelQuery || text.includes(modelQuery.toLowerCase());
    });
  }, [selected?.models, modelQuery]);
  const groupedModels = useMemo(() => groupModelsBySource(models), [models]);

  useEffect(() => {
    if (!selected) return;
    setDraft({
      enabled: selected.enabled,
      api: selected.api,
      apiKey: "",
      baseUrl: selected.base_url ?? "",
      selectedModel: selected.selected_model ?? selected.models[0]?.id ?? "",
      reasoningEffort: selected.model_settings?.reasoning_effort ?? "low",
      temperature: String(selected.model_settings?.temperature ?? 0),
      maxOutputTokens: String(selected.model_settings?.max_output_tokens ?? 4096)
    });
    setModelQuery("");
    setMessage(null);
  }, [selected?.provider_id]);

  async function loadProviders() {
    setBusy("load");
    try {
      const next = await getModelProviders();
      setPayload(next);
      const activeProviderId = next.active.provider_id;
      if (activeProviderId && next.providers.some((provider) => provider.provider_id === activeProviderId)) {
        setSelectedProviderId(activeProviderId);
      } else if (!next.providers.some((provider) => provider.provider_id === selectedProviderId)) {
        setSelectedProviderId(next.providers[0]?.provider_id ?? "openai");
      }
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "供应商配置读取失败" });
    } finally {
      setBusy(null);
    }
  }

  async function saveSelected(showMessage = true) {
    if (!selected) return false;
    setBusy("save");
    try {
      await updateModelProvider(selected.provider_id, {
        enabled: draft.enabled,
        api: draft.api,
        api_key: draft.apiKey ? draft.apiKey : undefined,
        base_url: draft.baseUrl,
        selected_model: draft.selectedModel,
        model_settings: modelSettingsPayload(selected, draft)
      });
      if (showMessage) setMessage({ tone: "ok", text: "供应商配置已保存" });
      await loadProviders();
      await onAuthRefresh();
      return true;
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "保存失败" });
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function fetchModels() {
    if (!selected) return;
    if (!canFetchSelected) {
      setMessage({ tone: "error", text: providerBlockingText(selected, draft, "拉取模型列表") });
      return;
    }
    const saved = await saveSelected(false);
    if (!saved) return;
    setBusy("fetch");
    try {
      const result = await fetchProviderModels(selected.provider_id);
      setMessage({ tone: result.ok ? "ok" : "error", text: result.ok ? "模型列表已更新" : "模型拉取失败，预置模型仍按未验证显示" });
      await loadProviders();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "模型拉取失败" });
    } finally {
      setBusy(null);
    }
  }

  async function activateModel(modelId: string) {
    if (!selected) return;
    if (!canActivateSelected) {
      setMessage({ tone: "error", text: providerBlockingText(selected, draft, "启用模型") });
      return;
    }
    setBusy(`activate-${modelId}`);
    try {
      await updateModelProvider(selected.provider_id, {
        enabled: draft.enabled,
        api: draft.api,
        api_key: draft.apiKey ? draft.apiKey : undefined,
        base_url: draft.baseUrl,
        selected_model: modelId,
        model_settings: modelSettingsPayload(selected, draft)
      });
      const next = await activateProviderModel(selected.provider_id, modelId);
      setPayload(next);
      setDraft((current) => ({ ...current, selectedModel: modelId }));
      setMessage({ tone: "ok", text: `当前抽取模型已切换为 ${selected.provider_id}/${modelId}` });
      await onAuthRefresh();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "模型启用失败" });
      await loadProviders();
    } finally {
      setBusy(null);
    }
  }

  async function addManualModel() {
    if (!selected || !manualModelId.trim()) return;
    const model: ProviderModel = { id: manualModelId.trim(), name: manualModelName.trim() || manualModelId.trim(), input: ["text"] };
    const customModels = selected.models
      .filter((item) => modelSource(item) === "custom" && item.id !== model.id)
      .map(modelForUpdate);
    setBusy("manual");
    try {
      await updateModelProvider(selected.provider_id, {
        api: draft.api,
        base_url: draft.baseUrl,
        selected_model: model.id,
        custom_models: [...customModels, model],
        model_settings: modelSettingsPayload(selected, draft)
      });
      setManualModelId("");
      setManualModelName("");
      setMessage({ tone: "ok", text: "手动模型已添加为自定义模型" });
      await loadProviders();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "模型添加失败" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="provider-manager">
      <div className="provider-manager-head">
        <div>
          <h3>模型供应商</h3>
          <p>选择供应商、保存凭据、测试连接，再从已拉取或手动添加的模型中启用抽取模型。</p>
        </div>
        <div className="provider-manager-stats" aria-label="供应商摘要">
          <span><strong>{activeProvider?.label ?? "-"}</strong><small>当前供应商</small></span>
          <span><strong>{runnableProviderCount}/{providers.length}</strong><small>可参与抽取</small></span>
          <span><strong>{verifiedProviderCount}</strong><small>已测试连接</small></span>
        </div>
      </div>

      <div className="provider-manager-body">
        <aside className="provider-sidebar">
          <div className="provider-search">
            <Search size={15} />
            <input aria-label="搜索供应商" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索供应商..." />
          </div>
          <div className="provider-list">
            {filteredProviders.map((provider) => (
              <button
                key={provider.provider_id}
                className={`provider-item ${provider.provider_id === selected?.provider_id ? "active" : ""}`}
                type="button"
                onClick={() => setSelectedProviderId(provider.provider_id)}
              >
                {providerIcon(provider)}
                <span>{provider.label}</span>
                {provider.active && <b>当前</b>}
                <i className={providerTone(provider)} title={providerStatusText(provider)} />
              </button>
            ))}
          </div>
        </aside>

        <div className="provider-detail">
          <div className="provider-detail-header">
            <div>
              <h4>{selected?.label ?? "模型供应商"}</h4>
              <p>{selected?.description ?? "配置供应商、API Key 与模型清单。"}</p>
            </div>
            <div className="provider-actions">
              <button
                className="icon-button"
                type="button"
                onClick={() => void fetchModels()}
                disabled={!selected || busy !== null || !canFetchSelected}
                title={selected && !canFetchSelected ? providerBlockingText(selected, draft, "拉取模型列表") : "测试连接并从供应商拉取模型列表"}
              >
                <RefreshCw size={16} className={busy === "fetch" ? "spin" : ""} /> 测试并拉取
              </button>
              <button className="icon-button primary" type="button" onClick={() => void saveSelected()} disabled={!selected || busy !== null}>
                <CheckCircle2 size={16} /> 保存
              </button>
            </div>
          </div>

          {message && (
            <div className={`settings-message ${message.tone}`}>
              {message.tone === "ok" ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              {message.text}
            </div>
          )}

          {selected && (
            <>
              <div className="provider-status-grid">
                <div>
                  <span>当前生效模型</span>
                  <strong>{payload?.active.model ?? selected.selected_model ?? "-"}</strong>
                  <small>{activeModelRef}</small>
                </div>
                <div>
                  <span>供应商状态</span>
                  <strong>{providerStatusText(selected, draft)}</strong>
                  <small>{selected.status_message ?? providerBlockingText(selected, draft, "参与抽取")}</small>
                </div>
                <div>
                  <span>连接测试</span>
                  <strong>{connectionStatusText(selected)}</strong>
                  <small>{selected.last_error ?? (selected.connected_at ? formatProviderTime(selected.connected_at) : "尚未测试连接")}</small>
                </div>
                <div>
                  <span>模型清单</span>
                  <strong>{modelCountText(selected)}</strong>
                  <small>已拉取 / 手动 / 预置</small>
                </div>
              </div>

              <div className="provider-form-grid">
                <label className="settings-field">
                  <span>API Key</span>
                  <input
                    className="settings-input"
                    value={draft.apiKey}
                    onChange={(event) => setDraft((current) => ({ ...current, apiKey: event.target.value }))}
                    placeholder={selected.api_key_masked ? `已保存：${selected.api_key_masked}` : selected.auth_env_vars[0] ?? "API Key"}
                    type="password"
                  />
                </label>
                <label className="settings-field">
                  <span>Base URL</span>
                  <input
                    className="settings-input"
                    value={draft.baseUrl}
                    onChange={(event) => setDraft((current) => ({ ...current, baseUrl: event.target.value }))}
                    disabled={!selected.base_url_editable}
                    placeholder={selected.default_base_url ?? "https://provider.example.com/v1"}
                  />
                </label>
                <label className="settings-field">
                  <span>API 类型</span>
                  {providerApiOptions(selected).length > 1 ? (
                    <select
                      className="settings-input"
                      value={draft.api}
                      onChange={(event) => setDraft((current) => ({ ...current, api: event.target.value }))}
                    >
                      {providerApiOptions(selected).map((api) => (
                        <option key={api} value={api}>{apiTypeLabel(api)}</option>
                      ))}
                    </select>
                  ) : (
                    <input className="settings-input" value={apiTypeLabel(draft.api)} readOnly />
                  )}
                </label>
                <label className="settings-toggle-row">
                  <span>参与抽取</span>
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
                  />
                </label>
              </div>

              <div className="provider-meta">
                <span>{credentialStatusText(selected, draft)}</span>
                <span>{selected.auth_env_vars.join(" / ") || "无需环境变量"}</span>
                <span>{selected.connected_at ? `上次测试 ${formatProviderTime(selected.connected_at)}` : "未测试连接"}</span>
                {selected.provider_id === "openai" && <span>中转 API：Responses 不通时切换为 OpenAI-compatible Chat；Base URL 以中转平台文档为准，常见为根地址或 /v1。</span>}
                {selected.last_error && <span className="danger">错误：{selected.last_error}</span>}
              </div>

              <div className="provider-model-options">
                <div className="provider-model-options-head">
                  <strong>模型参数</strong>
                  <small>{modelOptionsHelp(selected, draft.api)}</small>
                </div>
                <div className="provider-model-options-grid">
                  {optionSchema?.reasoning_effort && (
                    <label className="settings-field compact">
                      <span>推理深度</span>
                      <select
                        className="settings-input"
                        value={draft.reasoningEffort}
                        onChange={(event) => setDraft((current) => ({ ...current, reasoningEffort: event.target.value }))}
                      >
                        {optionSchema.reasoning_effort.map((effort) => (
                          <option key={effort} value={effort}>{reasoningEffortLabel(effort)}</option>
                        ))}
                      </select>
                    </label>
                  )}
                  {optionSchema?.temperature && (
                    <label className="settings-field compact">
                      <span>温度</span>
                      <input
                        className="settings-input"
                        type="number"
                        min={optionSchema.temperature.min}
                        max={optionSchema.temperature.max}
                        step={optionSchema.temperature.step ?? 0.1}
                        value={draft.temperature}
                        onChange={(event) => setDraft((current) => ({ ...current, temperature: event.target.value }))}
                      />
                    </label>
                  )}
                  {optionSchema?.max_output_tokens && (
                    <label className="settings-field compact">
                      <span>最大输出 Tokens</span>
                      <input
                        className="settings-input"
                        type="number"
                        min={optionSchema.max_output_tokens.min}
                        max={optionSchema.max_output_tokens.max}
                        step={optionSchema.max_output_tokens.step ?? 256}
                        value={draft.maxOutputTokens}
                        onChange={(event) => setDraft((current) => ({ ...current, maxOutputTokens: event.target.value }))}
                      />
                    </label>
                  )}
                </div>
              </div>

              <div className="provider-model-tools">
                <div className="provider-search wide">
                  <Search size={15} />
                  <input aria-label="搜索模型" value={modelQuery} onChange={(event) => setModelQuery(event.target.value)} placeholder="搜索模型..." />
                </div>
                <input
                  className="settings-input"
                  value={manualModelId}
                  onChange={(event) => setManualModelId(event.target.value)}
                  placeholder="Model ID"
                />
                <input
                  className="settings-input"
                  value={manualModelName}
                  onChange={(event) => setManualModelName(event.target.value)}
                  placeholder="显示名称"
                />
                <button className="icon-button" type="button" onClick={() => void addManualModel()} disabled={busy !== null || !manualModelId.trim()}>
                  <Plus size={16} /> 添加
                </button>
              </div>

              {selected.recommended_models?.length ? (
                <div className="provider-recommendations">
                  <span>推荐模型</span>
                  <div>
                    {selected.recommended_models.map((model) => (
                      <code key={model.id}>{model.id}</code>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="provider-model-list">
                {MODEL_SOURCE_ORDER.map((source) => {
                  const group = groupedModels.get(source) ?? [];
                  if (group.length === 0) return null;
                  return (
                    <div className="provider-model-group" key={source}>
                      <div className="provider-model-group-title">
                        <span>{modelSourceLabel(source)}</span>
                        <small>{modelSourceHelp(source)}</small>
                      </div>
                      {group.map((model) => {
                        const modelRef = `${selected.provider_id}/${model.id}`;
                        const isActive = payload?.active.model_ref === modelRef;
                        const canActivateModel = canActivateSelected && model.runnable !== false;
                        return (
                          <button
                            key={model.id}
                            className={`provider-model-row ${isActive ? "active" : ""}`}
                            type="button"
                            onClick={() => void activateModel(model.id)}
                            disabled={busy !== null || !canActivateModel}
                            title={!canActivateModel ? providerBlockingText(selected, draft, "启用模型") : `启用 ${modelRef}`}
                          >
                            <span>
                              <strong>{model.name ?? model.id}</strong>
                              <small>{modelRef}</small>
                            </span>
                            <span className="model-row-meta">
                              <em>{modelSourceBadge(model)}</em>
                              <small>{model.context_window ? `${model.context_window.toLocaleString()} 上下文` : "上下文未记录"}</small>
                              <i>{isActive ? "当前" : busy === `activate-${model.id}` ? "切换中" : canActivateModel ? "启用" : "不可启用"}</i>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  );
                })}
                {!models.length && <div className="provider-empty">未找到模型。填写凭据后测试并拉取，或手动添加 Model ID。</div>}
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
