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
