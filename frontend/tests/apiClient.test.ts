import { describe, it, expect, beforeAll, afterAll } from "vitest";
import * as api from "../src/shared/api/client";
import { ApiError, deleteCase, downloadCaseExport, getAuthStatus, listCases } from "../src/shared/api/client";

const originalFetch = globalThis.fetch;

beforeAll(() => {
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
      expect(init?.method).toBe("DELETE");
      return new Response(JSON.stringify({ detail: "Case not found" }), {
        status: 400,
        headers: { "Content-Type": "application/json" }
      });
    }

    throw new Error(`unexpected fetch: ${url}`);
  }) as typeof fetch;
});

afterAll(() => {
  globalThis.fetch = originalFetch;
});

describe("apiClient", () => {
  it("AuthStatus should allow backend llm modes", async () => {
    const auth = await getAuthStatus();
    expect(auth.model_auth.auth_mode).toBe("online");
  });

  it("listCases should preserve persisted review audit count", async () => {
    const cases = await listCases();
    expect(cases[0].audit_count).toBe(3);
  });

  it("downloadCaseExport should read backend filename", async () => {
    const exportFile = await downloadCaseExport("case-audit");
    expect(exportFile.filename).toBe("case-audit.xlsx");
  });

  it("downloadCaseExport should return workbook bytes", async () => {
    const exportFile = await downloadCaseExport("case-audit");
    expect(await exportFile.blob.text()).toBe("xlsx-bytes");
  });

  it("request failures should throw ApiError with status and detail", async () => {
    await expect(deleteCase("case-1")).rejects.toThrow(ApiError);
    try {
      await deleteCase("case-1");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(400);
      expect((error as ApiError).message).toBe("Case not found");
    }
  });

  it("client should not export removed auth URLs", () => {
    expect("loginUrl" in api).toBe(false);
    expect("logoutUrl" in api).toBe(false);
    expect("completeChatGptLogin" in api).toBe(false);
  });
});
