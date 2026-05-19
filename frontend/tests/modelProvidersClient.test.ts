import { describe, it, expect, beforeAll, afterAll } from "vitest";
import {
  ApiError,
  activateProviderModel,
  fetchProviderModels,
  getModelProviders,
  updateModelProvider
} from "../src/shared/api/client";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

const openAiProvider = {
  provider_id: "openai",
  label: "OpenAI",
  description: "OpenAI Responses API with strict JSON Schema outputs.",
  api: "openai-responses",
  default_api: "openai-responses",
  api_options: ["openai-responses", "openai-completions"],
  default_base_url: "https://api.openai.com/v1",
  base_url: "https://api.openai.com/v1",
  auth_env_vars: ["EYEX_OPENAI_API_KEY", "OPENAI_API_KEY"],
  auth_optional: false,
  base_url_editable: true,
  enabled: true,
  selected_model: "gpt-5.4",
  models: [
    {
      id: "gpt-5.4",
      name: "GPT-5.4",
      context_window: 400000,
      max_tokens: 4096,
      input: ["text"],
      source: "fetched",
      runnable: true
    }
  ],
  recommended_models: [
    {
      id: "gpt-5.4-mini",
      name: "GPT-5.4 Mini",
      context_window: 400000,
      max_tokens: 4096,
      input: ["text"],
      source: "preset",
      runnable: false
    }
  ],
  model_counts: {
    fetched: 1,
    custom: 0,
    preset: 3
  },
  model_settings: {
    reasoning_effort: "low",
    temperature: 0,
    max_output_tokens: 4096
  },
  option_schema: {
    reasoning_effort: ["minimal", "low", "medium", "high", "xhigh"],
    max_output_tokens: { min: 256, max: 8192, step: 256 }
  },
  api_key_configured: true,
  api_key_masked: "sk-...1234",
  credential_status: "configured",
  connection_status: "verified",
  runnable: true,
  status_message: "OpenAI is runnable.",
  last_error: null,
  connected_at: "2026-05-05T00:00:00Z",
  active: true
};

const openAiModelProfile = {
  profile_id: "provider_openai_gpt_5_4",
  label: "OpenAI / gpt-5.4",
  provider: "openai_compatible",
  provider_id: "openai",
  model_ref: "openai/gpt-5.4",
  api: "openai-responses",
  model: "gpt-5.4",
  base_url: "https://api.openai.com/v1",
  auth_env_vars: ["EYEX_OPENAI_API_KEY", "OPENAI_API_KEY"],
  auth_optional: false,
  auth_configured: true,
  response_format: "json_schema",
  fallbacks: ["local/conservative-local"],
  input: ["text"],
  context_window: 400000,
  cost: {
    input: 0,
    output: 0
  },
  compat: {
    provider: "openai"
  }
};

const originalFetch = globalThis.fetch;

beforeAll(() => {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/model-providers") && method === "GET") {
      return jsonResponse({
        active: {
          provider_id: "openai",
          model_ref: "openai/gpt-5.4",
          model: "gpt-5.4"
        },
        providers: [openAiProvider]
      });
    }

    if (url.endsWith("/api/model-providers/openai") && method === "PATCH") {
      return jsonResponse({
        ok: true,
        provider: openAiProvider
      });
    }

    if (url.endsWith("/api/model-providers/openai/models/fetch") && method === "POST") {
      return jsonResponse({
        ok: true,
        ...openAiProvider
      });
    }

    if (url.endsWith("/api/model-providers/active") && method === "PATCH") {
      return jsonResponse({
        ok: true,
        active: {
          provider_id: "openai",
          model_ref: "openai/gpt-5.4",
          model: "gpt-5.4"
        },
        providers: [openAiProvider],
        active_model: openAiModelProfile
      });
    }

    if (url.endsWith("/api/model-providers/broken") && method === "PATCH") {
      return jsonResponse({
        ok: true,
        provider: {
          provider_id: "broken",
          label: "Broken Provider",
          description: "Broken provider payload",
          api: "openai-completions",
          auth_env_vars: ["EYEX_COMPATIBLE_API_KEY"],
          auth_optional: false,
          base_url_editable: true,
          enabled: true,
          models: "oops",
          api_key_configured: false
        }
      });
    }

    throw new Error(`unexpected fetch: ${url}`);
  }) as typeof fetch;
});

afterAll(() => {
  globalThis.fetch = originalFetch;
});

describe("modelProvidersClient", () => {
  it("getModelProviders should preserve active provider", async () => {
    const providers = await getModelProviders();
    expect(providers.active.provider_id).toBe("openai");
  });

  it("getModelProviders should validate provider models", async () => {
    const providers = await getModelProviders();
    expect(providers.providers[0].models[0].id).toBe("gpt-5.4");
  });

  it("recommended models should be parsed", async () => {
    const providers = await getModelProviders();
    expect(providers.providers[0].recommended_models?.[0].source).toBe("preset");
  });

  it("updateModelProvider should parse provider details", async () => {
    const updated = await updateModelProvider("openai", {
      enabled: true,
      selected_model: "gpt-5.4"
    });
    expect(updated.provider.api_key_configured).toBe(true);
  });

  it("updateModelProvider should preserve metadata", async () => {
    const updated = await updateModelProvider("openai", {
      enabled: true,
      selected_model: "gpt-5.4"
    });
    expect(updated.provider.connected_at).toBe("2026-05-05T00:00:00Z");
  });

  it("fetchProviderModels should surface ok flag", async () => {
    const fetched = await fetchProviderModels("openai");
    expect(fetched.ok).toBe(true);
  });

  it("fetchProviderModels should return provider detail", async () => {
    const fetched = await fetchProviderModels("openai");
    expect(fetched.provider_id).toBe("openai");
  });

  it("fetchProviderModels should validate nested models", async () => {
    const fetched = await fetchProviderModels("openai");
    expect(fetched.models[0].source).toBe("fetched");
  });

  it("activateProviderModel should surface ok flag", async () => {
    const activated = await activateProviderModel("openai", "gpt-5.4");
    expect(activated.ok).toBe(true);
  });

  it("activateProviderModel should parse active model", async () => {
    const activated = await activateProviderModel("openai", "gpt-5.4");
    expect(activated.active_model.profile_id).toBe("provider_openai_gpt_5_4");
  });

  it("activateProviderModel should preserve provider list", async () => {
    const activated = await activateProviderModel("openai", "gpt-5.4");
    expect(activated.providers[0].provider_id).toBe("openai");
  });

  it("updateModelProvider should reject with validation error for broken payloads", async () => {
    await expect(updateModelProvider("broken", { enabled: false })).rejects.toThrow(ApiError);
    try {
      await updateModelProvider("broken", { enabled: false });
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(502);
      expect((error as ApiError).message).toContain("ModelProviderUpdateResponse.provider.models must be an array");
    }
  });
});
