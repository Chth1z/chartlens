import * as api from "../src/shared/api/client.js";
import { ApiError, deleteCase, downloadCaseExport, getAuthStatus, listCases } from "../src/shared/api/client.js";

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

async function assertRejectsApiError(action: () => Promise<unknown>, expectedMessage: string) {
  try {
    await action();
  } catch (error) {
    if (!(error instanceof ApiError)) {
      throw new Error("request failures should throw ApiError");
    }
    assertEqual(error.status, 400, "ApiError should expose response status");
    assertEqual(error.message, expectedMessage, "ApiError should expose FastAPI detail");
    return;
  }
  throw new Error("expected request to reject");
}

const originalFetch = globalThis.fetch;

globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input);
  if (url.endsWith("/api/auth/me")) {
    return new Response(
      JSON.stringify({
        enabled: false,
        auth_provider: "chatgpt",
        configured: true,
        missing_config: [],
        config_warnings: [],
        chatgpt_login_available: false,
        authenticated: true,
        user: { sub: "local", email: null, name: "Local user" },
        session_auth: {
          enabled: false,
          authenticated: true,
          provider: "local",
          user: { sub: "local", email: null, name: "Local user" },
          issued_at: null,
          expires_at: null,
          cookie_name: "eyex_session"
        },
        model_auth: {
          auth_mode: "online",
          provider: "deepseek",
          online_model_available: true,
          api_key_configured: true,
          chatgpt_codex_configured: false,
          token_cache_exists: false,
          token_cache_path: "",
          updated_at: null,
          expires_at: null,
          user: null
        }
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  }

  if (url.endsWith("/api/cases")) {
    return new Response(
      JSON.stringify([
        {
          case_id: "case-audit",
          filename: "case.txt",
          status: "completed",
          created_at: "2026-05-01T00:00:00Z",
          updated_at: "2026-05-01T00:00:00Z",
          result_count: 1,
          review_required_count: 0,
          audit_count: 3
        }
      ]),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  }

  if (url.endsWith("/api/cases/case-audit/export")) {
    return new Response("xlsx-bytes", {
      status: 200,
      headers: {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": 'attachment; filename="case-audit.xlsx"'
      }
    });
  }

  if (url.endsWith("/api/cases/case-1")) {
    assertEqual(init?.method, "DELETE", "deleteCase should use DELETE");
    return new Response(JSON.stringify({ detail: "Case not found" }), {
      status: 400,
      headers: { "Content-Type": "application/json" }
    });
  }

  throw new Error(`unexpected fetch: ${url}`);
}) as typeof fetch;

const auth = await getAuthStatus();
assertEqual(auth.model_auth.auth_mode, "online", "AuthStatus should allow backend llm modes");

const cases = await listCases();
assertEqual(cases[0].audit_count, 3, "listCases should preserve persisted review audit count");

const exportFile = await downloadCaseExport("case-audit");
assertEqual(exportFile.filename, "case-audit.xlsx", "downloadCaseExport should read backend filename");
assertEqual(await exportFile.blob.text(), "xlsx-bytes", "downloadCaseExport should return workbook bytes");

await assertRejectsApiError(() => deleteCase("case-1"), "Case not found");

assert(!("loginUrl" in api), "client should not export removed /api/auth/login URL");
assert(!("logoutUrl" in api), "client should not export removed /api/auth/logout URL");
assert(!("completeChatGptLogin" in api), "client should not export removed ChatGPT completion API");

globalThis.fetch = originalFetch;
