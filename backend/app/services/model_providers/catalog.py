from __future__ import annotations

import yaml

from app.core.settings import settings

from app.services.model_providers.types import ProviderCatalogEntry, ProviderModel


def _built_in_provider_catalog() -> list[ProviderCatalogEntry]:
    return [
        ProviderCatalogEntry(
            provider_id="openai",
            label="OpenAI",
            description="OpenAI Responses API with strict JSON Schema outputs.",
            api="openai-responses",
            api_options=["openai-responses", "openai-completions"],
            default_base_url="https://api.openai.com/v1",
            auth_env_vars=["EYEX_OPENAI_API_KEY", "OPENAI_API_KEY"],
            base_url_editable=True,
            default_models=[
                ProviderModel(id="gpt-5.4", name="GPT-5.4", context_window=400000, max_tokens=4096),
                ProviderModel(id="gpt-5.4-mini", name="GPT-5.4 Mini", context_window=400000, max_tokens=4096),
                ProviderModel(id="gpt-5.5", name="GPT-5.5", context_window=400000, max_tokens=4096),
            ],
            option_schema={
                "reasoning_effort": ["minimal", "low", "medium", "high", "xhigh"],
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="deepseek",
            label="DeepSeek",
            description="DeepSeek OpenAI-compatible chat completions.",
            api="openai-completions",
            default_base_url="https://api.deepseek.com",
            auth_env_vars=["EYEX_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"],
            base_url_editable=True,
            default_models=[
                ProviderModel(id="deepseek-v4-flash", name="DeepSeek V4 Flash", context_window=1000000, max_tokens=384000),
                ProviderModel(id="deepseek-v4-pro", name="DeepSeek V4 Pro", context_window=1000000, max_tokens=384000),
            ],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="anthropic",
            label="Anthropic",
            description="Claude native Messages API.",
            api="anthropic-messages",
            default_base_url="https://api.anthropic.com",
            auth_env_vars=["EYEX_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"],
            default_models=[
                ProviderModel(id="claude-opus-4-6", name="Claude Opus 4.6", context_window=200000, max_tokens=4096),
                ProviderModel(id="claude-sonnet-4-6", name="Claude Sonnet 4.6", context_window=200000, max_tokens=4096),
                ProviderModel(id="claude-haiku-4-6", name="Claude Haiku 4.6", context_window=200000, max_tokens=4096),
            ],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="google",
            label="Google Gemini",
            description="Google Gemini native generateContent API.",
            api="google-gemini",
            default_base_url="https://generativelanguage.googleapis.com",
            auth_env_vars=["EYEX_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"],
            default_models=[
                ProviderModel(id="gemini-3.1-pro-preview", name="Gemini 3.1 Pro", context_window=1000000, max_tokens=8192),
                ProviderModel(id="gemini-3-flash-preview", name="Gemini 3 Flash", context_window=1000000, max_tokens=8192),
                ProviderModel(id="gemini-2.5-flash", name="Gemini 2.5 Flash", context_window=1000000, max_tokens=8192),
            ],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="openrouter",
            label="OpenRouter",
            description="OpenAI-compatible router with broad model catalog.",
            api="openai-completions",
            default_base_url="https://openrouter.ai/api/v1",
            auth_env_vars=["EYEX_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"],
            default_models=[ProviderModel(id="auto", name="Auto")],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="moonshot",
            label="Moonshot",
            description="Kimi/Moonshot OpenAI-compatible API.",
            api="openai-completions",
            default_base_url="https://api.moonshot.ai/v1",
            auth_env_vars=["EYEX_MOONSHOT_API_KEY", "MOONSHOT_API_KEY"],
            default_models=[
                ProviderModel(id="kimi-k2.6", name="Kimi K2.6", context_window=200000),
                ProviderModel(id="kimi-k2-thinking", name="Kimi K2 Thinking", context_window=200000),
            ],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="qwen",
            label="Qwen / DashScope",
            description="Alibaba DashScope OpenAI-compatible endpoint.",
            api="openai-completions",
            default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            auth_env_vars=["EYEX_QWEN_API_KEY", "QWEN_API_KEY", "DASHSCOPE_API_KEY", "MODELSTUDIO_API_KEY"],
            default_models=[
                ProviderModel(id="qwen3.5-plus", name="Qwen 3.5 Plus", context_window=1000000),
                ProviderModel(id="qwen3.5-coder-plus", name="Qwen 3.5 Coder Plus", context_window=1000000),
            ],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="zai",
            label="Z.AI / GLM",
            description="Z.AI GLM OpenAI-compatible API.",
            api="openai-completions",
            default_base_url="https://open.bigmodel.cn/api/paas/v4",
            auth_env_vars=["EYEX_ZAI_API_KEY", "ZAI_API_KEY", "GLM_API_KEY"],
            default_models=[ProviderModel(id="glm-5.1", name="GLM 5.1", context_window=200000)],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="azure-openai",
            label="Azure OpenAI",
            description="Azure OpenAI v1-compatible endpoint; use deployment name as model.",
            api="openai-completions",
            default_base_url=None,
            auth_env_vars=["EYEX_AZURE_OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"],
            default_models=[],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="ollama",
            label="Ollama",
            description="Local Ollama OpenAI-compatible endpoint.",
            api="openai-completions",
            default_base_url="http://127.0.0.1:11434/v1",
            auth_env_vars=["EYEX_OLLAMA_API_KEY", "OLLAMA_API_KEY"],
            auth_optional=True,
            default_models=[ProviderModel(id="llama3.3", name="Llama 3.3")],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="custom",
            label="Custom Provider",
            description="Any OpenAI-compatible /v1/chat/completions provider.",
            api="openai-completions",
            default_base_url=None,
            auth_env_vars=["EYEX_COMPATIBLE_API_KEY"],
            default_models=[],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
    ]


def provider_catalog() -> list[ProviderCatalogEntry]:
    configured = _load_provider_catalog_from_yaml()
    return configured or _built_in_provider_catalog()


def _load_provider_catalog_from_yaml() -> list[ProviderCatalogEntry]:
    directory = settings.config_dir / "model_providers"
    if not directory.exists():
        return []
    entries: list[ProviderCatalogEntry] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            items = raw if isinstance(raw, list) else raw.get("providers", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    entries.append(ProviderCatalogEntry.model_validate(item))
        except Exception:
            continue
    return entries


def _require_entry(provider_id: str) -> ProviderCatalogEntry:
    for entry in provider_catalog():
        if entry.provider_id == provider_id:
            return entry
    raise ValueError(f"Unknown provider: {provider_id}")
