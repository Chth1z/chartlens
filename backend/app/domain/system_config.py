from __future__ import annotations

from pydantic import BaseModel, Field


class ImagePreprocessConfig(BaseModel):
    enabled: bool = True
    grayscale: bool = True
    autocontrast: bool = True
    denoise: bool = False
    threshold: bool = False


class OcrProfileConfig(BaseModel):
    label: str
    engine_priority: list[str] = Field(default_factory=lambda: ["rapidocr", "paddleocr"])
    pdf_dpi: int = Field(default=300, ge=100, le=600)
    preprocess: ImagePreprocessConfig = Field(default_factory=ImagePreprocessConfig)
    max_parallel_pages: int = Field(default=1, ge=1, le=8)
    low_confidence_threshold: float = Field(default=0.80, ge=0.0, le=1.0)


class OcrConfig(BaseModel):
    default_profile: str = "accurate"
    profiles: dict[str, OcrProfileConfig]

    def profile(self, name: str | None = None) -> OcrProfileConfig:
        profile_name = name or self.default_profile
        return self.profiles.get(profile_name) or self.profiles[self.default_profile]


class LayoutProfileConfig(BaseModel):
    provider_priority: list[str] = Field(default_factory=lambda: ["heuristic_sections"])
    layout_models: dict[str, str] = Field(default_factory=dict)
    min_region_score: float = Field(default=0.35, ge=0.0, le=1.0)
    section_confidence_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    section_aliases: dict[str, list[str]] = Field(default_factory=dict)


class LayoutConfig(BaseModel):
    default_profile: str = "clinical_sections"
    profiles: dict[str, LayoutProfileConfig]

    def profile(self, name: str | None = None) -> LayoutProfileConfig:
        profile_name = name or self.default_profile
        return self.profiles.get(profile_name) or self.profiles[self.default_profile]


class LlmProfileConfig(BaseModel):
    model_env: str
    reasoning_effort: str = "low"
    prompt_cache_key: str = "chartlens-clinical-extraction-v1"
    max_fields_per_call: int = Field(default=12, ge=1)


class VisionFallbackConfig(BaseModel):
    enabled: bool = True
    requires_manual_approval: bool = True
    allowed_asset_kinds: list[str] = Field(default_factory=lambda: ["page_image", "crop"])


class LlmConfig(BaseModel):
    default_profile: str = "standard"
    profiles: dict[str, LlmProfileConfig]
    vision_fallback: VisionFallbackConfig = Field(default_factory=VisionFallbackConfig)


class MedicalDictionariesConfig(BaseModel):
    history_fields: dict[str, list[str]] = Field(default_factory=dict)
    negation_terms: list[str] = Field(default_factory=list)
    unknown_terms: list[str] = Field(default_factory=list)


class EvaluationConfig(BaseModel):
    gold_sample_target_min: int = 50
    gold_sample_target_max: int = 100
    auto_accept_precision_target: float = 0.95
    reviewed_export_accuracy_target: float = 0.99
    ocr_cer_relative_improvement_target: float = 0.20


class SystemConfig(BaseModel):
    version: str
    ocr: OcrConfig
    layout: LayoutConfig
    llm: LlmConfig
    medical_dictionaries: MedicalDictionariesConfig = Field(default_factory=MedicalDictionariesConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
