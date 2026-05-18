import { Bot, Cloud, KeyRound, Server, Zap } from "lucide-react";
import type { ModelProvider, ProviderModel } from "../../shared/types/api";

export type DraftState = {
  enabled: boolean;
  api: string;
  apiKey: string;
  baseUrl: string;
  selectedModel: string;
  reasoningEffort: string;
  temperature: string;
  maxOutputTokens: string;
};

export type ModelSource = "fetched" | "custom" | "unknown";
export type ProviderOptionSchema = NonNullable<ModelProvider["option_schema"]>;

export const MODEL_SOURCE_ORDER: ModelSource[] = ["fetched", "custom", "unknown"];
const OPENAI_CHAT_OPTION_SCHEMA: ProviderOptionSchema = {
  temperature: { min: 0, max: 1, step: 0.1 },
  max_output_tokens: { min: 256, max: 8192, step: 256 }
};

export function providerIcon(provider: ModelProvider) {
  if (provider.api === "openai-responses") return <Bot size={16} />;
  if (provider.api === "anthropic-messages") return <Zap size={16} />;
  if (provider.api === "google-gemini") return <Cloud size={16} />;
  if (provider.auth_optional) return <Server size={16} />;
  return <KeyRound size={16} />;
}

export function modelSettingsPayload(provider: ModelProvider, draft: DraftState) {
  const payload: NonNullable<ModelProvider["model_settings"]> = {};
  const schema = providerOptionSchema(provider, draft.api);
  if (schema?.reasoning_effort) payload.reasoning_effort = draft.reasoningEffort;
  if (schema?.temperature) payload.temperature = Number.parseFloat(draft.temperature);
  if (schema?.max_output_tokens) payload.max_output_tokens = Number.parseInt(draft.maxOutputTokens, 10);
  return payload;
}

export function providerApiOptions(provider: ModelProvider) {
  return provider.api_options?.length ? provider.api_options : [provider.api];
}

export function providerOptionSchema(provider: ModelProvider, api: string): ProviderOptionSchema | undefined {
  if (provider.provider_id === "openai" && api === "openai-completions") return OPENAI_CHAT_OPTION_SCHEMA;
  return provider.option_schema;
}

export function modelOptionsHelp(provider: ModelProvider, api: string) {
  if (api === "openai-responses") return "OpenAI Responses 支持 reasoning.effort，适合官方 API 或支持 Responses 的中转。";
  if (api === "anthropic-messages") return "Claude 当前提供温度和输出长度控制。";
  if (api === "google-gemini") return "Gemini 当前提供温度和输出长度控制。";
  if (provider.provider_id === "openai") return "OpenAI-compatible Chat 适合大多数只兼容 /v1/chat/completions 的中转 API。";
  return "OpenAI-compatible 供应商统一提供温度和输出长度控制。";
}

export function reasoningEffortLabel(value: string) {
  const labels: Record<string, string> = {
    minimal: "Minimal - 最低延迟",
    low: "Low - 高效抽取",
    medium: "Medium - 平衡",
    high: "High - 复杂推理",
    xhigh: "XHigh - 最强推理"
  };
  return labels[value] ?? value;
}

export function formatProviderTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function providerHasCredential(provider: ModelProvider, draft?: DraftState) {
  return provider.auth_optional || provider.api_key_configured || Boolean(draft?.apiKey.trim());
}

export function providerHasBaseUrl(provider: ModelProvider, draft?: DraftState) {
  const api = draft?.api ?? provider.api;
  if (api !== "openai-completions" && api !== "openai-responses") return true;
  return Boolean(draft?.baseUrl.trim() || provider.base_url || provider.default_base_url);
}

export function providerIsRunnable(provider: ModelProvider) {
  if (typeof provider.runnable === "boolean") return provider.runnable;
  return provider.enabled && (provider.auth_optional || provider.api_key_configured) && providerHasBaseUrl(provider);
}

export function providerBlockingText(provider: ModelProvider, draft: DraftState | undefined, action: string) {
  if (draft && !draft.enabled) return `开启“参与抽取”后才能${action}。`;
  if (!providerHasBaseUrl(provider, draft)) return `填写 Base URL 后才能${action}。`;
  if (!providerHasCredential(provider, draft)) return `填写并保存 API Key 后才能${action}。`;
  if (providerHasCredential(provider, draft) && providerHasBaseUrl(provider, draft)) return `${provider.label} 已具备${action}条件。`;
  return provider.status_message ?? `当前配置暂不能${action}。`;
}

export function credentialStatusText(provider: ModelProvider, draft?: DraftState) {
  if (provider.auth_optional && !provider.api_key_configured && !draft?.apiKey.trim()) return "API Key 可选，本地服务可用";
  if (provider.api_key_configured) return "API Key 已配置";
  if (draft?.apiKey.trim()) return "API Key 待保存";
  return `缺少 ${provider.auth_env_vars[0] ?? "API Key"}`;
}

export function providerStatusText(provider: ModelProvider, draft?: DraftState) {
  if (draft && !draft.enabled) return "已关闭";
  if (provider.last_error) return "连接有错误";
  if (providerHasCredential(provider, draft) && providerHasBaseUrl(provider, draft)) return "可参与抽取";
  return "不可参与抽取";
}

export function providerTone(provider: ModelProvider) {
  if (!provider.enabled) return "disabled";
  if (provider.last_error) return "error";
  if (providerIsRunnable(provider)) return "ready";
  return "warning";
}

export function connectionStatusText(provider: ModelProvider) {
  if (provider.last_error) return "失败";
  if (provider.connected_at) return "已测试";
  return "未测试";
}

export function modelCountText(provider: ModelProvider) {
  const counts = provider.model_counts;
  if (counts) return `${counts.fetched} / ${counts.custom} / ${counts.preset}`;
  const total = provider.models.length;
  return `${total} / 0 / 0`;
}

export function apiTypeLabel(api: string) {
  if (api === "openai-responses") return "OpenAI Responses";
  if (api === "openai-completions") return "OpenAI-compatible Chat";
  if (api === "anthropic-messages") return "Anthropic Messages";
  if (api === "google-gemini") return "Google Gemini";
  if (api === "disabled") return "本地规则";
  return api;
}

export function modelSource(model: ProviderModel): ModelSource {
  if (model.source === "fetched" || model.source === "custom") return model.source;
  return "unknown";
}

export function groupModelsBySource(models: ProviderModel[]) {
  const groups = new Map<ModelSource, ProviderModel[]>();
  models.forEach((model) => {
    const source = modelSource(model);
    groups.set(source, [...(groups.get(source) ?? []), model]);
  });
  return groups;
}

export function modelSourceLabel(source: ModelSource) {
  if (source === "fetched") return "已拉取模型";
  if (source === "custom") return "手动添加模型";
  return "来源未标记";
}

export function modelSourceHelp(source: ModelSource) {
  if (source === "fetched") return "来自供应商接口，已通过测试连接返回。";
  if (source === "custom") return "由本机配置保存，适合私有部署或未开放列表的模型。";
  return "后端未返回来源，启用前请先测试连接。";
}

export function modelSourceBadge(model: ProviderModel) {
  const source = modelSource(model);
  if (source === "fetched") return "已拉取";
  if (source === "custom") return "手动";
  return "来源未知";
}

export function modelForUpdate(model: ProviderModel): ProviderModel {
  return {
    id: model.id,
    name: model.name,
    context_window: model.context_window,
    max_tokens: model.max_tokens,
    input: model.input ?? ["text"]
  };
}
