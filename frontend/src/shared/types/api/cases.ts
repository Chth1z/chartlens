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
