from fastapi.testclient import TestClient

from app.main import app


def _success_schema(openapi: dict, path: str, method: str = "get") -> dict:
    return openapi["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]


def test_openapi_exposes_frontend_contract_models():
    client = TestClient(app)
    openapi = client.get("/openapi.json").json()

    expected_refs = {
        ("/api/auth/me", "get"): "#/components/schemas/AuthStatusResponse",
        ("/api/settings/runtime", "get"): "#/components/schemas/RuntimeSettingsResponse",
        ("/api/settings/system", "get"): "#/components/schemas/SystemSettingsResponse",
        ("/api/cases/{case_id}/document-ir", "get"): "#/components/schemas/DocumentIrResponse",
        ("/api/cases/{case_id}/diagnostics", "get"): "#/components/schemas/CaseDiagnosticsResponse",
    }

    for (path, method), ref in expected_refs.items():
        assert _success_schema(openapi, path, method)["$ref"] == ref


def test_openapi_does_not_expose_removed_auth_routes():
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/auth/login" not in paths
    assert "/api/auth/logout" not in paths
    assert "/api/auth/chatgpt/complete" not in paths
