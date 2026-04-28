from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "EYES Clinical Extraction"
    database_url: str = "sqlite:///./storage/eyes.sqlite3"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: Path = Path("./storage")
    sync_pipeline: bool = False
    case_workers: int = Field(default=1, ge=1, le=4)
    ocr_page_workers: int | None = Field(default=None, ge=1, le=8)
    llm_workers: int = Field(default=1, ge=1, le=4)
    llm_case_context_budget: int = Field(default=3200, ge=500, le=12000)
    openai_api_key: str | None = None
    openai_auth_mode: str = Field(default="auto", pattern="^(auto|api_key|chatgpt|disabled)$")
    openai_standard_model: str = "gpt-5.4-mini"
    openai_thorough_model: str = "gpt-5.5"
    model_mode: str = Field(default="standard", pattern="^(standard|thorough)$")
    ocr_profile: str = "accurate"
    layout_profile: str = "chinese_inpatient_v1"
    auto_accept_threshold: float = 0.90
    review_threshold: float = 0.60
    oauth_enabled: bool = False
    oauth_provider: str = Field(default="chatgpt", pattern="^(chatgpt|oidc)$")
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_authorization_url: str | None = None
    oauth_token_url: str | None = None
    oauth_userinfo_url: str | None = None
    oauth_redirect_uri: str = "http://127.0.0.1:8000/api/auth/callback"
    oauth_scopes: str = "openid email profile"
    oauth_allowed_email_domains: str = ""
    oauth_session_secret: str = "change-me-for-production"
    oauth_session_cookie: str = "eyes_session"
    oauth_state_cookie: str = "oauth_state"
    oauth_session_ttl_seconds: int = 60 * 60 * 12
    frontend_url: str = "http://127.0.0.1:5173"
    chatgpt_oauth_client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann"
    chatgpt_oauth_authorization_url: str = "https://auth.openai.com/oauth/authorize"
    chatgpt_oauth_token_url: str = "https://auth.openai.com/oauth/token"
    chatgpt_oauth_callback_port: int = 1455
    chatgpt_oauth_start_callback_server: bool = True
    chatgpt_token_cache_path: Path = Path("./storage/auth/chatgpt_tokens.json")
    chatgpt_token_refresh_margin_seconds: int = 300
    chatgpt_codex_responses_url: str = "https://chatgpt.com/backend-api/codex/responses"

    model_config = SettingsConfigDict(env_prefix="EYES_", env_file=".env", extra="ignore")


settings = Settings()
