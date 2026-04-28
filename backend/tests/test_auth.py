from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.auth import create_session_cookie
from app.services.auth import AuthUser


client = TestClient(app)


def test_auth_me_reports_disabled_auth_by_default():
    settings.oauth_enabled = False

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["authenticated"] is True


def test_auth_me_reports_missing_oauth_configuration(monkeypatch):
    monkeypatch.setattr(settings, "oauth_enabled", True)
    monkeypatch.setattr(settings, "oauth_provider", "oidc", raising=False)
    monkeypatch.setattr(settings, "oauth_client_id", "")
    monkeypatch.setattr(settings, "oauth_authorization_url", "")
    monkeypatch.setattr(settings, "oauth_token_url", "")
    monkeypatch.setattr(settings, "oauth_userinfo_url", "")

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["configured"] is False
    assert "EYES_OAUTH_CLIENT_ID" in payload["missing_config"]
    assert "EYES_OAUTH_AUTHORIZATION_URL" in payload["missing_config"]


def test_oauth_login_reports_configuration_error(monkeypatch):
    monkeypatch.setattr(settings, "oauth_enabled", True)
    monkeypatch.setattr(settings, "oauth_provider", "oidc", raising=False)
    monkeypatch.setattr(settings, "oauth_client_id", "")
    monkeypatch.setattr(settings, "oauth_authorization_url", "")
    monkeypatch.setattr(settings, "oauth_token_url", "")
    monkeypatch.setattr(settings, "oauth_userinfo_url", "")

    response = client.get("/api/auth/login", follow_redirects=False)

    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["error"] == "OAuth is enabled but not fully configured"
    assert "EYES_OAUTH_CLIENT_ID" in payload["detail"]["missing_config"]


def test_enabled_oauth_rejects_case_access_without_session(monkeypatch):
    monkeypatch.setattr(settings, "oauth_enabled", True)
    monkeypatch.setattr(settings, "oauth_provider", "oidc", raising=False)
    monkeypatch.setattr(settings, "oauth_client_id", "client")
    monkeypatch.setattr(settings, "oauth_authorization_url", "https://idp.example/authorize")

    response = client.get("/api/cases")

    assert response.status_code == 401


def test_oauth_login_redirects_to_provider_with_state(monkeypatch):
    monkeypatch.setattr(settings, "oauth_enabled", True)
    monkeypatch.setattr(settings, "oauth_provider", "oidc", raising=False)
    monkeypatch.setattr(settings, "oauth_client_id", "client")
    monkeypatch.setattr(settings, "oauth_authorization_url", "https://idp.example/authorize")
    monkeypatch.setattr(settings, "oauth_token_url", "https://idp.example/token")
    monkeypatch.setattr(settings, "oauth_userinfo_url", "https://idp.example/userinfo")
    monkeypatch.setattr(settings, "oauth_redirect_uri", "http://127.0.0.1:8000/api/auth/callback")
    monkeypatch.setattr(settings, "oauth_scopes", "openid email profile")

    response = client.get("/api/auth/login", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://idp.example/authorize?")
    assert "oauth_state=" in response.headers["set-cookie"]


def test_signed_session_cookie_allows_case_access_when_oauth_enabled(monkeypatch):
    monkeypatch.setattr(settings, "oauth_enabled", True)
    monkeypatch.setattr(settings, "oauth_provider", "oidc", raising=False)
    cookie = create_session_cookie({"sub": "user-1", "email": "researcher@example.com", "name": "Researcher"})

    response = client.get("/api/cases", cookies={"eyes_session": cookie})

    assert response.status_code == 200


def test_chatgpt_oauth_mode_needs_no_manual_oidc_configuration(monkeypatch):
    monkeypatch.setattr(settings, "oauth_enabled", True)
    monkeypatch.setattr(settings, "oauth_provider", "chatgpt", raising=False)
    monkeypatch.setattr(settings, "oauth_client_id", "")
    monkeypatch.setattr(settings, "oauth_authorization_url", "")
    monkeypatch.setattr(settings, "oauth_token_url", "")
    monkeypatch.setattr(settings, "oauth_userinfo_url", "")

    response = client.get("/api/auth/me")

    payload = response.json()
    assert payload["enabled"] is True
    assert payload["configured"] is True
    assert payload["auth_provider"] == "chatgpt"
    assert payload["chatgpt_login_available"] is True


def test_chatgpt_oauth_login_redirects_to_openai_authorize(monkeypatch):
    monkeypatch.setattr(settings, "oauth_enabled", True)
    monkeypatch.setattr(settings, "oauth_provider", "chatgpt", raising=False)
    monkeypatch.setattr(settings, "chatgpt_oauth_start_callback_server", False, raising=False)

    response = client.get("/api/auth/login", follow_redirects=False)

    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("https://auth.openai.com/oauth/authorize?")
    assert "client_id=app_EMoamEEZ73f0CkXaXp7hrann" in location
    assert "code_challenge_method=S256" in location
    assert "codex_cli_simplified_flow=true" in location


def test_chatgpt_login_ticket_is_idempotent_for_browser_retries():
    from app.services import chatgpt_oauth

    ticket = "ticket-for-browser-retry"
    chatgpt_oauth._tickets[ticket] = chatgpt_oauth.ChatGptTicket(
        user=AuthUser(sub="user-1", email="user@example.com"),
        next_path="/",
        created_at=chatgpt_oauth.time.time(),
    )

    first = chatgpt_oauth.complete_chatgpt_ticket(ticket)
    second = chatgpt_oauth.complete_chatgpt_ticket(ticket)

    assert first is not None
    assert second is not None
    assert first[0].email == "user@example.com"
    assert second[0].email == "user@example.com"


def test_chatgpt_complete_ignores_expired_ticket_when_session_is_already_valid(monkeypatch):
    monkeypatch.setattr(settings, "oauth_enabled", True)
    monkeypatch.setattr(settings, "oauth_provider", "chatgpt")
    cookie = create_session_cookie({"sub": "user-1", "email": "user@example.com"})

    response = client.get("/api/auth/chatgpt/complete?ticket=expired", cookies={"eyes_session": cookie})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["user"]["email"] == "user@example.com"
