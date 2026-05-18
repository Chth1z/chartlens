export interface AuthStatus {
  enabled: boolean;
  auth_provider: "chatgpt" | "oidc";
  configured: boolean;
  missing_config: string[];
  config_warnings: string[];
  chatgpt_login_available: boolean;
  authenticated: boolean;
  user: {
    sub: string;
    email?: string | null;
    name?: string | null;
  } | null;
  session_auth: {
    enabled: boolean;
    authenticated: boolean;
    provider: "local" | "chatgpt" | "oidc" | string;
    user: {
      sub: string;
      email?: string | null;
      name?: string | null;
    } | null;
    issued_at: number | null;
    expires_at: number | null;
    cookie_name: string;
  };
  model_auth: {
    auth_mode: "auto" | "online" | "local" | "disabled";
    provider: "openai_api_key" | "chatgpt_codex" | "local_fallback" | "deepseek" | "openai_compatible" | string;
    online_model_available: boolean;
    api_key_configured: boolean;
    chatgpt_codex_configured: boolean;
    token_cache_exists: boolean;
    token_cache_path: string;
    updated_at: string | number | null;
    expires_at: string | number | null;
    user?: {
      sub?: string | null;
      email?: string | null;
      name?: string | null;
    } | null;
  };
}
