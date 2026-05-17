// Runtime contract schemas for the EYEX API boundary.
//
// These schemas back the runtime validation enforced in `client.ts`. They
// describe the *shape* the frontend insists on; mismatches surface as
// ApiError(502) so backend/frontend drift is visible in tests instead of
// hiding behind loose typing.
//
// Conventions:
// - Use `.passthrough()` on response-root objects so future backend additions
//   do not break the frontend.
// - Type aliases in `../types/api.ts` remain the canonical types consumed by
//   the rest of the frontend; the schemas are validators that produce values
//   compatible with those aliases.

import { z } from "zod";

const stringOrNull = z.string().nullable();
const numberOrNull = z.number().nullable();
const booleanOrNull = z.boolean().nullable();

// --- Provider models / selection ---

export const providerModelSchema = z
  .object({
    id: z.string(),
    name: stringOrNull.optional(),
    context_window: numberOrNull.optional(),
    max_tokens: numberOrNull.optional(),
    input: z.array(z.string()).optional(),
    source: stringOrNull.optional(),
    runnable: booleanOrNull.optional()
  })
  .passthrough();

export const modelProviderSelectionSchema = z
  .object({
    provider_id: stringOrNull.optional(),
    model_ref: stringOrNull.optional(),
    model: stringOrNull.optional()
  })
  .passthrough();

// --- Model profile ---

export const modelProfileSchema = z
  .object({
    profile_id: z.string(),
    provider: z.string(),
    model: z.string(),
    label: stringOrNull.optional(),
    provider_id: stringOrNull.optional(),
    model_ref: stringOrNull.optional(),
    api: stringOrNull.optional(),
    base_url: stringOrNull.optional(),
    api_key_env: stringOrNull.optional(),
    auth_env_vars: z.array(z.string()).optional(),
    auth_optional: z.boolean().optional(),
    auth_configured: z.boolean().optional(),
    response_format: stringOrNull.optional(),
    fallbacks: z.array(z.string()).optional(),
    input: z.array(z.string()).optional(),
    context_window: numberOrNull.optional(),
    context_tokens: numberOrNull.optional(),
    cost: z.record(z.string(), z.unknown()).optional(),
    compat: z.record(z.string(), z.unknown()).optional()
  })
  .passthrough();

// --- Model provider catalog entry ---

export const modelProviderSchema = z
  .object({
    provider_id: z.string(),
    label: z.string(),
    description: z.string(),
    api: z.string(),
    default_api: stringOrNull.optional(),
    api_options: z.array(z.string()).optional(),
    default_base_url: stringOrNull.optional(),
    base_url: stringOrNull.optional(),
    auth_env_vars: z.array(z.string()),
    auth_optional: z.boolean(),
    base_url_editable: z.boolean(),
    enabled: z.boolean(),
    api_key_configured: z.boolean(),
    selected_model: stringOrNull.optional(),
    models: z.array(providerModelSchema),
    recommended_models: z.array(providerModelSchema).optional(),
    model_counts: z.record(z.string(), z.unknown()).optional(),
    model_settings: z.record(z.string(), z.unknown()).optional(),
    option_schema: z.record(z.string(), z.unknown()).optional(),
    api_key_masked: stringOrNull.optional(),
    credential_status: stringOrNull.optional(),
    connection_status: stringOrNull.optional(),
    runnable: booleanOrNull.optional(),
    status_message: stringOrNull.optional(),
    last_error: stringOrNull.optional(),
    connected_at: stringOrNull.optional(),
    active: booleanOrNull.optional()
  })
  .passthrough();

// --- Provider response shapes ---

export const modelProvidersResponseSchema = z
  .object({
    active: modelProviderSelectionSchema,
    providers: z.array(modelProviderSchema)
  })
  .passthrough();

export const modelProviderUpdateResponseSchema = z
  .object({
    ok: z.boolean(),
    provider: modelProviderSchema
  })
  .passthrough();

// `fetchProviderModels` returns a provider object spread alongside `ok`.
// We accept the provider shape with an extra `ok` boolean.
export const modelProviderFetchResponseSchema = modelProviderSchema.and(
  z.object({ ok: z.boolean() })
);

export const modelProviderActivationResponseSchema = z
  .object({
    ok: z.boolean(),
    active: modelProviderSelectionSchema,
    providers: z.array(modelProviderSchema),
    active_model: modelProfileSchema
  })
  .passthrough();

// --- Auth status ---

const userIdentitySchema = z
  .object({
    sub: z.string(),
    email: stringOrNull.optional(),
    name: stringOrNull.optional()
  })
  .passthrough();

export const authStatusSchema = z
  .object({
    enabled: z.boolean(),
    auth_provider: z.string(),
    configured: z.boolean(),
    missing_config: z.array(z.string()),
    config_warnings: z.array(z.string()),
    chatgpt_login_available: z.boolean(),
    authenticated: z.boolean(),
    user: userIdentitySchema.nullable().optional(),
    session_auth: z
      .object({
        enabled: z.boolean(),
        authenticated: z.boolean(),
        provider: z.string(),
        user: userIdentitySchema.nullable().optional(),
        issued_at: numberOrNull.optional(),
        expires_at: numberOrNull.optional(),
        cookie_name: z.string()
      })
      .passthrough(),
    model_auth: z
      .object({
        auth_mode: z.enum(["auto", "online", "local", "disabled"]),
        provider: z.string(),
        online_model_available: z.boolean(),
        api_key_configured: z.boolean(),
        chatgpt_codex_configured: z.boolean(),
        token_cache_exists: z.boolean(),
        token_cache_path: z.string(),
        updated_at: z.union([z.string(), z.number()]).nullable().optional(),
        expires_at: z.union([z.string(), z.number()]).nullable().optional(),
        user: userIdentitySchema.nullable().optional()
      })
      .passthrough()
  })
  .passthrough();

// --- Settings response wrappers (only require the wrapper key exists) ---

export const systemSettingsResponseSchema = z
  .object({ system_config: z.unknown() })
  .passthrough();

export const runtimeSettingsResponseSchema = z
  .object({
    runtime_settings: z.unknown(),
    restart_required_hints: z.array(z.string()).optional()
  })
  .passthrough();
