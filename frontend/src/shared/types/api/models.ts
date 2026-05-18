export interface ModelProfile {
  profile_id: string;
  label?: string | null;
  provider: "openai_responses" | "openai_compatible" | "anthropic_messages" | "google_gemini" | "disabled" | string;
  provider_id?: string | null;
  model_ref?: string | null;
  api?: "openai-responses" | "openai-completions" | "anthropic-messages" | "google-gemini" | "disabled" | string | null;
  model: string;
  base_url?: string | null;
  api_key_env?: string | null;
  auth_env_vars?: string[];
  auth_optional?: boolean;
  auth_configured?: boolean;
  response_format?: "json_schema" | "json_object" | string;
  fallbacks?: string[];
  input?: string[];
  context_window?: number | null;
  context_tokens?: number | null;
  cost?: Record<string, number>;
  compat?: Record<string, unknown>;
}

export interface ModelProfilesResponse {
  active_profile_id: string;
  active_model_ref?: string;
  fallbacks?: string[];
  resolved_chain?: string[];
  profiles: ModelProfile[];
  env: {
    openai_api_key_configured: boolean;
    deepseek_api_key_configured: boolean;
    compatible_api_key_configured: boolean;
    compatible_base_url_configured: boolean;
    compatible_model_configured: boolean;
    providers?: Record<string, { configured: boolean; auth_optional: boolean; env_vars: string[] }>;
  };
}

export interface ModelProfileSelectionResponse extends ModelProfilesResponse {
  ok: boolean;
  active: ModelProfile;
}

export interface ProviderModel {
  id: string;
  name?: string | null;
  context_window?: number | null;
  max_tokens?: number | null;
  input?: string[];
  source?: "fetched" | "custom" | "preset" | string | null;
  runnable?: boolean | null;
}

export interface ModelProviderSelection {
  provider_id?: string | null;
  model_ref?: string | null;
  model?: string | null;
}

export interface ModelProvider {
  provider_id: string;
  label: string;
  description: string;
  api: "openai-responses" | "openai-completions" | "anthropic-messages" | "google-gemini" | "disabled" | string;
  default_api?: string;
  api_options?: string[];
  default_base_url?: string | null;
  base_url?: string | null;
  auth_env_vars: string[];
  auth_optional: boolean;
  base_url_editable: boolean;
  enabled: boolean;
  selected_model?: string | null;
  models: ProviderModel[];
  recommended_models?: ProviderModel[];
  model_counts?: {
    fetched: number;
    custom: number;
    preset: number;
  };
  model_settings?: {
    reasoning_effort?: string;
    temperature?: number;
    max_output_tokens?: number;
  };
  option_schema?: {
    reasoning_effort?: string[];
    temperature?: { min: number; max: number; step?: number };
    max_output_tokens?: { min: number; max: number; step?: number };
  };
  api_key_configured: boolean;
  api_key_masked?: string | null;
  credential_status?: "configured" | "optional" | "missing_api_key" | "missing_base_url" | "disabled" | string;
  connection_status?: "verified" | "not_tested" | "error" | string;
  runnable?: boolean;
  status_message?: string;
  last_error?: string | null;
  connected_at?: string | null;
  active?: boolean;
}

export interface ModelProvidersResponse {
  active: ModelProviderSelection;
  providers: ModelProvider[];
}

export interface ModelProviderUpdatePayload {
  enabled?: boolean;
  api?: string | null;
  api_key?: string | null;
  base_url?: string | null;
  selected_model?: string | null;
  custom_models?: ProviderModel[];
  model_settings?: {
    reasoning_effort?: string;
    temperature?: number;
    max_output_tokens?: number;
  };
}

export interface ModelProviderUpdateResponse {
  ok: boolean;
  provider: ModelProvider;
}

export interface ModelProviderFetchResponse extends ModelProvider {
  ok: boolean;
}

export interface ModelProviderActivationResponse extends ModelProvidersResponse {
  ok: boolean;
  active_model: ModelProfile;
}
