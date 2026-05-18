import type { FieldDefinition } from "./fields";

export interface SystemSettingsResponse {
  system_config: {
    path: string;
    version: string;
    ocr_default_profile: string;
    ocr_active_profile?: Record<string, unknown>;
    ocr_accelerator?: string;
    available_accelerators?: Record<string, unknown>;
    ocr_strategy?: string;
    ocr_profile_engines?: string[];
    ocr_document_ai_configured?: boolean;
    ocr_openai_model?: string;
    ocr_openai_configured?: boolean;
    layout_default_profile: string;
    llm_default_profile: string;
    ocr_profiles: string[];
    layout_profiles: string[];
    llm_profiles: string[];
    vision_fallback_enabled: boolean;
  };
}

export interface FieldDictionarySettingsResponse {
  field_dictionary: {
    path: string;
    version: string;
    field_count: number;
    phase_1_count: number;
    fields: FieldDefinition[];
  };
}

export interface RuntimeSettingsResponse {
  runtime_settings: {
    database_url: string;
    storage_dir: string;
    sync_pipeline: boolean;
    case_workers: number;
    ocr_page_workers: number;
    llm_workers: number;
    ocr_profile: string;
    ocr_active_profile?: Record<string, unknown>;
    ocr_accelerator?: string;
    available_accelerators?: Record<string, unknown>;
    ocr_strategy?: string;
    ocr_profile_engines?: string[];
    ocr_document_ai_configured?: boolean;
    ocr_openai_model?: string;
    ocr_openai_configured?: boolean;
    layout_profile: string;
    model_mode: string;
    openai_auth_mode: string;
    oauth_enabled: boolean;
    oauth_provider: string;
    chatgpt_token_cache_path: string;
    services?: RuntimeServices;
  };
  restart_required_hints: string[];
}

export interface RuntimeServices {
  backend?: RuntimeServiceStatus;
  ocr?: RuntimeServiceStatus;
  frontend?: RuntimeServiceStatus;
}

export interface RuntimeServiceStatus {
  key: string;
  label: string;
  ready: boolean | null;
  status: "ready" | "not_ready" | "not_running" | "not_configured" | "external" | string;
  summary: string;
  details?: string[];
  endpoint?: string;
  health_url?: string;
  profile_id?: string;
  pipeline_stages?: string[];
  stage_models?: Record<string, unknown>;
  checks?: RuntimeServiceCheck[];
  actions?: RuntimeServiceAction[];
  sidecar?: Record<string, unknown>;
}

export interface RuntimeServiceCheck {
  key: string;
  label: string;
  ready: boolean;
  status: string;
  engine_id?: string;
  reason?: string;
}

export interface RuntimeServiceAction {
  label: string;
  command: string;
  description?: string;
}

export interface SettingsValidationPayload {
  system_config_yaml?: string | null;
  field_dictionary_yaml?: string | null;
}

export interface SettingsValidationResponse {
  ok: boolean;
  validation_errors: string[];
  restart_required_hints: string[];
}

export interface MaintenanceResult {
  ok: boolean;
  affected_count?: number;
  message?: string;
}
