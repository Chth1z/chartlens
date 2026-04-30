from fastapi.testclient import TestClient

from app.core.settings import settings
from app.main import app
from app.services import model_providers


def test_model_profiles_include_deepseek_and_custom(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    client = TestClient(app)

    response = client.get("/api/model-profiles")

    assert response.status_code == 200
    payload = response.json()
    profile_ids = {profile["profile_id"] for profile in payload["profiles"]}
    assert {
        "openai_structured",
        "deepseek_v4_flash",
        "deepseek_v4_pro",
        "openai_compatible_custom",
        "openrouter_auto",
        "ollama_local",
        "local_disabled",
    } <= profile_ids
    assert "lmstudio_local" not in profile_ids
    assert "vllm_local" not in profile_ids
    model_refs = {profile["model_ref"] for profile in payload["profiles"]}
    assert {"openai/gpt-5.4", "deepseek/deepseek-v4-flash", "openrouter/auto"} <= model_refs
    assert payload["resolved_chain"][0] == "openai/gpt-5.4"
    assert "compatible_base_url_configured" in payload["env"]
    assert "compatible_model_configured" in payload["env"]
    assert "providers" in payload["env"]


def test_model_profile_selection_is_persisted(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    client = TestClient(app)

    response = client.patch("/api/model-profiles/active", json={"profile_id": "deepseek_v4_flash"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_profile_id"] == "deepseek_v4_flash"
    assert payload["active_model_ref"] == "deepseek/deepseek-v4-flash"
    assert payload["active"]["provider"] == "openai_compatible"
    assert (tmp_path / "model_selection.json").exists()

    reread = client.get("/api/model-profiles")
    assert reread.status_code == 200
    assert reread.json()["active_profile_id"] == "deepseek_v4_flash"


def test_model_profile_selection_accepts_openclaw_style_model_ref(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    client = TestClient(app)

    response = client.patch("/api/model-profiles/active", json={"profile_id": "deepseek/deepseek-v4-pro"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_profile_id"] == "deepseek_v4_pro"
    assert payload["active_model_ref"] == "deepseek/deepseek-v4-pro"
    assert payload["resolved_chain"][0] == "deepseek/deepseek-v4-pro"


def test_frontend_settings_endpoints(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    client = TestClient(app)

    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/project-config").status_code == 200
    assert client.get("/api/settings/system").status_code == 200
    assert client.get("/api/settings/runtime").status_code == 200
    assert client.post("/api/settings/validate", json={}).json()["ok"] is True


def test_model_provider_catalog_and_activation(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    client = TestClient(app)

    payload = client.get("/api/model-providers").json()
    provider_ids = {provider["provider_id"] for provider in payload["providers"]}
    assert {"openai", "anthropic", "google", "deepseek", "openrouter", "ollama", "custom"} <= provider_ids
    assert {"groq", "together", "mistral", "xai", "siliconflow", "volcengine", "lmstudio", "vllm"}.isdisjoint(provider_ids)
    openai = next(provider for provider in payload["providers"] if provider["provider_id"] == "openai")
    assert openai["base_url_editable"] is True
    assert openai["default_base_url"] == "https://api.openai.com/v1"
    assert openai["api_options"] == ["openai-responses", "openai-completions"]
    assert "reasoning_effort" in openai["option_schema"]
    deepseek = next(provider for provider in payload["providers"] if provider["provider_id"] == "deepseek")
    assert deepseek["models"] == []
    assert {model["source"] for model in deepseek["recommended_models"]} == {"preset"}
    assert {model["runnable"] for model in deepseek["recommended_models"]} == {False}
    assert "runnable" in deepseek
    assert deepseek["model_counts"]["preset"] >= 1

    update = client.patch(
        "/api/model-providers/custom",
        json={
            "api_key": "test-key",
            "base_url": "http://127.0.0.1:9999/v1",
            "selected_model": "demo-model",
            "custom_models": [{"id": "demo-model", "name": "Demo Model"}],
            "model_settings": {"temperature": 0.2, "max_output_tokens": 2048},
        },
    )
    assert update.status_code == 200
    assert update.json()["provider"]["api_key_masked"] == "********"
    assert update.json()["provider"]["model_settings"]["temperature"] == 0.2

    active = client.patch("/api/model-providers/active", json={"provider_id": "custom", "model_id": "demo-model"})
    assert active.status_code == 200
    assert active.json()["active"]["model_ref"] == "custom/demo-model"

    reread = client.get("/api/model-profiles").json()
    assert reread["active_model_ref"] == "custom/demo-model"
    assert reread["resolved_chain"][0] == "custom/demo-model"
    assert "provider_custom_demo_model" in {profile["profile_id"] for profile in reread["profiles"]}


def test_provider_fetch_keeps_all_returned_models_and_can_activate_any(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"id": "gpt-5.4", "name": "GPT-5.4"},
                    "relay-free-model",
                    {"model_id": "relay-special", "display_name": "Relay Special"},
                    {"id": "provider/nested-model"},
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.requests = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def get(self, url, headers=None):
            self.requests.append((url, headers))
            return FakeResponse()

    monkeypatch.setattr(model_providers.httpx, "Client", FakeClient)
    client = TestClient(app)
    update = client.patch(
        "/api/model-providers/openai",
        json={
            "api": "openai-completions",
            "api_key": "test-key",
            "base_url": "https://relay.example/v1",
        },
    )
    assert update.status_code == 200
    assert update.json()["provider"]["api"] == "openai-completions"
    assert "temperature" in update.json()["provider"]["option_schema"]

    fetched = client.post("/api/model-providers/openai/models/fetch")

    assert fetched.status_code == 200
    provider = fetched.json()
    model_ids = {model["id"] for model in provider["models"]}
    assert {"gpt-5.4", "relay-free-model", "relay-special", "provider/nested-model"} <= model_ids
    assert provider["model_counts"]["fetched"] == 4

    active = client.patch("/api/model-providers/active", json={"provider_id": "openai", "model_id": "relay-special"})

    assert active.status_code == 200
    assert active.json()["active_model"]["provider"] == "openai_compatible"
    assert active.json()["active"]["model_ref"] == "openai/relay-special"

    reread = client.get("/api/model-profiles").json()
    assert reread["resolved_chain"][0] == "openai/relay-special"


def test_model_provider_activation_requires_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr("app.services.model_providers.explicit_api_keys_for_profile", lambda profile: [])
    client = TestClient(app)

    update = client.patch(
        "/api/model-providers/anthropic",
        json={"custom_models": [{"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"}]},
    )
    assert update.status_code == 200

    response = client.patch("/api/model-providers/active", json={"provider_id": "anthropic", "model_id": "claude-sonnet-4-6"})

    assert response.status_code == 400
    assert "API Key" in response.text
