export type ReviewBand = "auto_accept" | "needs_review" | "unknown";

export interface EvidencePack {
  field_key: string;
  pack_hash: string;
  rank: number;
  block_id: string;
  text: string;
  context_text: string;
  page: number;
  bbox: number[];
  section_label: string;
  document_kind: string;
  ocr_confidence: number;
  score: number;
  match_terms: string[];
  score_reason?: string | null;
  negated: boolean;
  uncertain: boolean;
  family_context: boolean;
  token_estimate: number;
  neighbor_block_ids: string[];
}

export interface FieldResult {
  field_key: string;
  field_group_key?: string | null;
  raw_value: string | null;
  normalized_code: string | null;
  confidence: number;
  evidence_text: string | null;
  evidence_span?: string | null;
  evidence_block_id?: string | null;
  evidence_type?: string | null;
  page: number | null;
  bbox: number[];
  reasoning_summary: string | null;
  review_required: boolean;
  error_code: string | null;
  validator_messages?: string[];
  provenance?: Record<string, unknown>;
  acceptance_reason?: string | null;
  risk_level?: "low" | "medium" | "high" | "critical";
  evidence_candidates?: Array<{
    block_id: string;
    field_key?: string | null;
    candidate_value?: string | null;
    normalized_code?: string | null;
    evidence_text?: string | null;
    field_label_seen?: string | null;
    source_type?: string;
    document_region?: string | null;
    visual_confirmed?: boolean;
    block_ids?: string[];
    forbidden_inference_flags?: string[];
    conflicts?: Array<Record<string, unknown>>;
    text: string;
    page: number;
    bbox: number[];
    confidence?: number;
    section_label: string;
    document_kind: string;
    ocr_confidence: number;
    score: number;
    match_terms?: string[];
    score_reason?: string | null;
    pack_hash?: string | null;
    context_text?: string | null;
    token_estimate?: number;
    negated?: boolean;
    uncertain?: boolean;
    family_context?: boolean;
    rank?: number;
  }>;
  evidence_packs?: EvidencePack[];
  model_profile_id?: string | null;
  ocr_engine?: string | null;
  validation_state?: "unknown" | "accepted" | "needs_review" | "rejected" | "reviewed";
}

export interface OcrBlock {
  block_id?: string;
  page: number;
  reading_order?: number;
  text: string;
  bbox: number[];
  confidence: number;
  block_type?: DocumentFragment["block_type"];
  section_label?: string;
  document_kind?: string;
  render_dpi?: number | null;
  preprocess_profile?: string | null;
}

export interface OcrQuality {
  page_count: number;
  ocr_block_count: number;
  fragment_count: number;
  avg_ocr_confidence: number;
  low_confidence_block_count: number;
  quality_band: "good" | "fair" | "poor";
  needs_vision_fallback: boolean;
  input_kind?: string | null;
  ocr_adapter?: string | null;
  ocr_engine?: string | null;
  ocr_intelligent_status?: string | null;
  ocr_attempted_engines?: string[];
  ocr_unavailable_engines?: string[];
  ocr_unavailable_reasons?: Record<string, string>;
  ocr_engine_errors?: Record<string, string>;
  ocr_page_quality?: Array<{
    page: number;
    kind: string;
    char_count: number;
    avg_confidence: number;
    quality_band: "good" | "fair" | "poor" | string;
    cache_status?: string;
    engine?: string;
    failure_reason?: string;
  }>;
}

export interface ProcessingRun {
  run_id: string;
  status: string;
  system_config_version?: string | null;
  field_dictionary_version?: string | null;
  ocr_profile: string;
  layout_profile: string;
  llm_profile: string;
  parser_mode: string;
  page_count: number;
  ocr_block_count: number;
  fragment_count: number;
  avg_ocr_confidence: number;
  low_confidence_block_count: number;
  quality_band: string;
  auto_accept_count: number;
  review_required_count: number;
  unknown_count: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  step_timings: Record<string, number | string | number[] | Record<string, number> | Record<string, string>>;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface DocumentFragment {
  page: number;
  reading_order: number;
  text: string;
  bbox: number[];
  confidence: number;
  section_name: string;
  block_type: "line" | "paragraph" | "text" | "table" | "title" | "form_field" | "cell" | "checkbox" | "selection_mark" | "key_value";
  source_engine?: string | null;
  source_page_kind?: string;
  ocr_profile?: string | null;
  layout_profile?: string | null;
  quality_flags?: string[];
  source_kind: "pdf_text" | "ocr" | "pp_structure" | "manual" | "intelligent_document";
  document_kind?: string;
  layout_region_id?: string | null;
  line_group_id?: string | null;
  coordinate_system?: string | null;
  merge_confidence?: number | null;
  merge_flags?: string[];
  canonical_source_ids?: string[];
  layout_type?: string | null;
  section_confidence?: number;
  parser_version?: string;
  render_dpi?: number | null;
  preprocess_profile?: string | null;
}

export interface ModelCallLog {
  call_id: string;
  run_id?: string;
  provider: string;
  model: string;
  mode: string;
  stage?: string;
  field_keys: string[];
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  status: string;
  error_code: string | null;
  error_message?: string | null;
  fallback_attempts?: number;
  fallback_failures?: number;
  fallback_errors?: string[];
  created_at: string;
  llm_cache_status?: "hit" | "miss" | string | null;
  llm_cache_key?: string | null;
}

export interface VisionFallbackRecord {
  request_id: string;
  case_id: string;
  field_key?: string | null;
  page: number;
  bbox: number[];
  status: string;
  reason: string;
  reviewer: string;
  manual_redaction_confirmed?: boolean;
  created_at: string;
  approved_at: string | null;
}

export interface CaseDiagnostics {
  case_id: string;
  quality: OcrQuality;
  latest_run: ProcessingRun | null;
  run_count: number;
  runs: ProcessingRun[];
  events?: Array<{
    run_id: string;
    step_name: string;
    status: string;
    payload: Record<string, unknown>;
    error_code: string | null;
    error_message: string | null;
    duration_ms: number;
    started_at: string;
    completed_at: string | null;
  }>;
  fragments: DocumentFragment[];
  model_calls: ModelCallLog[];
  vision_requests: VisionFallbackRecord[];
  config: {
    ocr_default_profile: string;
    layout_default_profile: string;
    llm_default_profile: string;
    vision_fallback_enabled: boolean;
    vision_fallback_requires_manual_approval: boolean;
    gold_sample_target_min: number;
  };
}

export interface CaseRecord {
  case_id: string;
  filename: string;
  status: "queued" | "processing" | "ocr" | "extracting" | "completed" | "degraded" | "failed" | "archived";
  error_message: string | null;
  created_at: string;
  updated_at: string;
  result_count: number;
  review_required_count: number;
  results: FieldResult[];
  ocr_blocks: OcrBlock[];
  audit_count: number;
  latest_run?: ProcessingRun | null;
  quality?: OcrQuality;
}

export interface CaseSummary {
  case_id: string;
  filename: string;
  status: CaseRecord["status"];
  created_at: string;
  updated_at: string;
  result_count: number;
  review_required_count: number;
  audit_count: number;
}

export interface DocumentIrResponse {
  blocks: OcrBlock[];
  sections?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
}

export interface SourceOcrResponse {
  blocks: OcrBlock[];
  metadata?: Record<string, unknown>;
}

export interface FieldDefinition {
  key: string;
  field_group_key?: string | null;
  label: string;
  export_header: string;
  allowed_codes: string[];
  type?: string;
  extract_mode?: string;
  source_sections?: string[];
  synonyms?: string[];
  evidence_priority?: string[];
  rule_strategy?: Record<string, unknown>;
  review_policy?: string;
  max_evidence_items?: number;
  evidence_window_chars?: number;
  llm?: {
    enabled: boolean;
    evidence_budget: number;
    max_evidence_items: number;
    prompt_profile: string;
    skip_when_no_evidence?: boolean;
  };
  evidence_policy?: {
    allowed_evidence_sources: string[];
    forbidden_inference_sources: string[];
    source_priority: string[];
    conflict_policy: string;
    implicit_negative_policy: string;
    require_visual_confirmation: boolean;
    pass_criteria: string[];
    high_risk: boolean;
  };
  phase: number;
}

export interface FieldDictionary {
  version: string;
  fields: FieldDefinition[];
}

export interface FieldGroupDefinition {
  key: string;
  label: string;
  source_sections: string[];
  prompt_profile: string;
  max_context_chars: number;
  semantic_strategy: string;
}

export interface EvidenceDisplayConfig {
  basic_field_labels: string[];
  section_labels: string[];
  inline_record_labels: string[];
  section_tones: Record<string, string[]>;
  document_title_patterns: string[];
  common_ocr_repairs: Array<{ pattern: string; replacement: string }>;
}

export interface ProjectConfig {
  app_profile: {
    profile_id: string;
    version?: string;
    label: string;
    terms: Record<string, string>;
    default_document_profile_id: string;
    default_extraction_schema_id: string;
    default_export_template_id: string;
    ocr_engine_policy?: string;
  };
  document_profile: {
    profile_id: string;
    version?: string;
    label: string;
    section_aliases: Record<string, string[]>;
    frontend: EvidenceDisplayConfig;
  };
  extraction_schema: {
    schema_id: string;
    version: string;
    label: string;
    extraction_strategy?: string;
    field_groups: FieldGroupDefinition[];
    fields: FieldDefinition[];
  };
  export_template: {
    template_id: string;
    version?: string;
    label: string;
    empty_value: string;
    unknown_value?: string | null;
    columns: Array<{ field_key: string; header: string; empty_value: string; unknown_value?: string | null }>;
  };
}

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
