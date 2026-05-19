from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STORAGE_DIR = PROJECT_ROOT / "var" / "storage"
DEFAULT_DATABASE_URL = f"sqlite:///{(DEFAULT_STORAGE_DIR / 'eyex.sqlite3').as_posix()}"


class Settings(BaseSettings):
    app_name: str = "EYEX"
    database_url: str = DEFAULT_DATABASE_URL
    storage_dir: Path = DEFAULT_STORAGE_DIR
    config_dir: Path = PROJECT_ROOT / "config"
    document_profile: str = "medical_inpatient_zh"
    ocr_profile: str = "windows_radeon_balanced"
    extraction_schema: str = "medical_inpatient_zh"
    export_template: str = "medical_inpatient_zh"
    model_profile: str = "openai_structured"
    llm_mode: Literal["auto", "online", "local", "disabled"] = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4"
    openai_reasoning_effort: str = "low"
    openai_timeout_seconds: float = 90.0
    model_key_cooldown_seconds: float = 60.0
    ocr_strategy: Literal["intelligent"] = "intelligent"
    ocr_intelligent_min_chars: int = 80
    ocr_intelligent_min_confidence: float = 0.65
    ocr_accelerator: str = "auto"
    ocr_directml_model_dir: Path | None = None
    ocr_directml_enable_experimental: bool = False
    ocr_route_version: str = "ocr-route-v1"
    ocr_document_ai_url: str | None = None
    ocr_document_ai_api_key: str | None = None
    ocr_document_ai_timeout_seconds: float = 900.0
    ocr_engine_timeout_seconds: float = 120.0
    ocr_paddleocr_vl_url: str | None = None
    ocr_paddleocr_vl_api_key: str | None = None
    ocr_openai_model: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    compatible_api_key: str | None = None
    compatible_base_url: str | None = None
    compatible_model: str | None = None
    case_workers: int = 2
    llm_workers: int = 2
    auto_process_uploads: bool = True
    allow_remote_access: bool = False
    local_api_token: str | None = None
    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_upload_suffixes: str = ".pdf,.png,.jpg,.jpeg,.txt,.md"
    max_pending_cases: int = 16
    allow_plaintext_provider_keys: bool = False
    otel_enabled: bool = False
    otel_endpoint: str = ""
    otel_service_name: str = "eyex-backend"
    config_watch: bool = True
    evidence_embeddings: bool = False
    evidence_embedding_weight: float = 2.0
    multimodal_evidence: bool = False
    multimodal_max_pages: int = 4
    presidio_enabled: bool = False
    log_format: Literal["json", "console"] = "json"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="EYEX_",
        extra="ignore",
    )


settings = Settings()
