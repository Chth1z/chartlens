# Re-exports for backward-compatible monkey-patching. Tests and consumers
# expect these names to live on `app.services.llm_provider.adapters`. The
# provider submodules dereference these via the package so test
# monkey-patches keep working unchanged after the E0-004 split.
from app.services.model_auth import api_keys_for_profile  # noqa: F401
from app.services.llm_provider.cache import (  # noqa: F401
    _llm_cache_key,
    _read_llm_result_cache,
    _write_llm_result_cache,
    _read_evidence_candidate_cache,
    _write_evidence_candidate_cache,
)
from app.services.llm_provider.payloads import (  # noqa: F401
    _responses_evidence_first_payload,
    _chat_completions_payload,
)

from app.services.llm_provider.adapters.openai_responses import OpenAIResponsesProvider
from app.services.llm_provider.adapters.openai_compatible import OpenAICompatibleChatProvider
from app.services.llm_provider.adapters.anthropic import AnthropicMessagesProvider
from app.services.llm_provider.adapters.gemini import GoogleGeminiProvider

__all__ = [
    "OpenAIResponsesProvider",
    "OpenAICompatibleChatProvider",
    "AnthropicMessagesProvider",
    "GoogleGeminiProvider",
]
