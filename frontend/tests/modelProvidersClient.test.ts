import {
  ApiError,
  activateProviderModel,
  fetchProviderModels,
  getModelProviders,
  updateModelProvider
} from "../src/shared/api/client.js";

function assertEqual<T>(actual: T, expected: T, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, received ${actual}`);
  }
}

function assert(condition: unknown, message: string) {
  if (!condition) {
    throw new Error(message);
  }
}

async function assertRejectsApiError(action: () => Promise<unknown>, expectedStatus: number, expectedMessage: string) {
  try {
    await action();
  } catch (error) {
    if (!(error instanceof ApiError)) {
      throw new Error("request failures should throw ApiError");
    }
    assertEqual(error.status, expectedStatus, "ApiError should expose response status");
    assert(
      error.message.includes(expectedMessage),
      `ApiError should include "${expectedMessage}", received "${error.message}"`
    );
    return;
  }
  throw new Error("expected request to reject");
}

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

try {
  const providers = await getModelProviders();
  assertEqual(providers.active.provider_id, "openai", "getModelProviders should preserve active provider");
  assertEqual(providers.providers[0].models[0].id, "gpt-5.4", "getModelProviders should validate provider models");
  assertEqual(providers.providers[0].recommended_models?.[0].source, "preset", "recommended models should be parsed");

  const updated = await updateModelProvider("openai", {
    enabled: true,
    selected_model: "gpt-5.4"
  });
  assertEqual(updated.provider.api_key_configured, true, "updateModelProvider should parse provider details");
  assertEqual(updated.provider.connected_at, "2026-05-05T00:00:00Z", "updateModelProvider should preserve metadata");

  const fetched = await fetchProviderModels("openai");
  assertEqual(fetched.ok, true, "fetchProviderModels should surface ok flag");
  assertEqual(fetched.provider_id, "openai", "fetchProviderModels should return provider detail");
  assertEqual(fetched.models[0].source, "fetched", "fetchProviderModels should validate nested models");

  const activated = await activateProviderModel("openai", "gpt-5.4");
  assertEqual(activated.ok, true, "activateProviderModel should surface ok flag");
  assertEqual(activated.active_model.profile_id, "provider_openai_gpt_5_4", "activateProviderModel should parse active model");
  assertEqual(activated.providers[0].provider_id, "openai", "activateProviderModel should preserve provider list");

  await assertRejectsApiError(
    () => updateModelProvider("broken", { enabled: false }),
    502,
    "ModelProviderUpdateResponse.provider.models must be an array"
  );
} finally {
  globalThis.fetch = originalFetch;
}
