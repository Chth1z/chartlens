export type ReviewBand = "auto_accept" | "needs_review" | "unknown";

export interface FieldResult {
  field_key: string;
  raw_value: string | null;
  normalized_code: string | null;
  confidence: number;
  evidence_text: string | null;
  page: number | null;
  bbox: number[];
  reasoning_summary: string | null;
  review_required: boolean;
  error_code: string | null;
}

export interface OcrBlock {
  page: number;
  text: string;
  bbox: number[];
  confidence: number;
}

export interface OcrQuality {
  page_count: number;
  ocr_block_count: number;
  fragment_count: number;
  avg_ocr_confidence: number;
  low_confidence_block_count: number;
  quality_band: "good" | "fair" | "poor";
  needs_vision_fallback: boolean;
}

export interface ProcessingRun {
  run_id: string;
  status: string;
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
  step_timings: Record<string, number>;
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
  block_type: "line" | "paragraph" | "text" | "table" | "title";
  source_kind: "pdf_text" | "ocr" | "pp_structure" | "manual";
}

export interface ModelCallLog {
  call_id: string;
  provider: string;
  model: string;
  mode: string;
  field_keys: string[];
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  status: string;
  error_code: string | null;
  created_at: string;
}

export interface VisionFallbackRecord {
  request_id: string;
  case_id: string;
  page: number;
  bbox: number[];
  status: string;
  reason: string;
  reviewer: string;
  created_at: string;
  approved_at: string | null;
}

export interface CaseDiagnostics {
  case_id: string;
  quality: OcrQuality;
  latest_run: ProcessingRun | null;
  run_count: number;
  runs: ProcessingRun[];
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
  file_hash: string;
  status: "queued" | "processing" | "ocr" | "extracting" | "processed" | "degraded" | "failed";
  error_message: string | null;
  created_at: string;
  results: FieldResult[];
  ocr_blocks: OcrBlock[];
  audit_count: number;
  latest_run?: ProcessingRun | null;
  quality?: OcrQuality;
}

export interface FieldDefinition {
  key: string;
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
    trigger_statuses: string[];
    evidence_budget: number;
    allow_image_crop: boolean;
    prompt_profile: string;
  };
  phase: number;
}

export interface FieldDictionary {
  version: string;
  fields: FieldDefinition[];
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
  model_auth: {
    auth_mode: "auto" | "api_key" | "chatgpt" | "disabled";
    provider: "openai_api_key" | "chatgpt_codex" | "local_fallback";
    online_model_available: boolean;
    api_key_configured: boolean;
    chatgpt_codex_configured: boolean;
  };
}
