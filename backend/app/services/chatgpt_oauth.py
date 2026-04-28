from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from app.core.config import settings
from app.services.auth import AuthUser
from app.services.chatgpt_token_store import save_chatgpt_tokens


@dataclass
class ChatGptFlow:
    verifier: str
    next_path: str
    created_at: float


@dataclass
class ChatGptTicket:
    user: AuthUser
    next_path: str
    created_at: float


_flows: dict[str, ChatGptFlow] = {}
_tickets: dict[str, ChatGptTicket] = {}
_completed_tickets: dict[str, ChatGptTicket] = {}
_server: ThreadingHTTPServer | None = None
_server_lock = threading.Lock()


def begin_chatgpt_login(next_path: str = "/") -> str:
    if settings.chatgpt_oauth_start_callback_server:
        ensure_chatgpt_callback_server()
    verifier = _token(48)
    state = _token(32)
    _flows[state] = ChatGptFlow(verifier=verifier, next_path=_safe_next_path(next_path), created_at=time.time())
    _cleanup()
    query = urlencode(
        {
            "client_id": settings.chatgpt_oauth_client_id,
            "redirect_uri": _callback_url(),
            "response_type": "code",
            "scope": "openid email profile offline_access",
            "state": state,
            "code_challenge": _code_challenge(verifier),
            "code_challenge_method": "S256",
            "codex_cli_simplified_flow": "true",
        }
    )
    return f"{settings.chatgpt_oauth_authorization_url}?{query}"


def complete_chatgpt_ticket(ticket: str) -> tuple[AuthUser, str] | None:
    _cleanup()
    payload = _tickets.pop(ticket, None)
    if payload is None:
        payload = _completed_tickets.get(ticket)
    else:
        _completed_tickets[ticket] = payload
    if payload is None:
        return None
    return payload.user, payload.next_path


def ensure_chatgpt_callback_server() -> None:
    global _server
    with _server_lock:
        if _server is not None:
            return
        try:
            _server = ThreadingHTTPServer(("127.0.0.1", settings.chatgpt_oauth_callback_port), _CallbackHandler)
        except OSError as exc:
            raise RuntimeError(
                f"ChatGPT OAuth callback port {settings.chatgpt_oauth_callback_port} is already in use."
            ) from exc
        thread = threading.Thread(target=_server.serve_forever, daemon=True)
        thread.start()


class _CallbackHandler(BaseHTTPRequestHandler):
    server_version = "EYESChatGptOAuth/0.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_error(404)
            return

        params = parse_qs(parsed.query)
        code = _single(params, "code")
        state = _single(params, "state")
        if not code or not state:
            self._redirect_error("missing_code_or_state")
            return

        flow = _flows.pop(state, None)
        if flow is None or time.time() - flow.created_at > 600:
            self._redirect_error("expired_state")
            return

        try:
            token_payload = _exchange_code(code, flow.verifier)
            user = _user_from_token_payload(token_payload)
            save_chatgpt_tokens(token_payload, user)
        except Exception:
            self._redirect_error("token_exchange_failed")
            return

        ticket = _token(32)
        _tickets[ticket] = ChatGptTicket(user=user, next_path=flow.next_path, created_at=time.time())
        self._redirect(f"{settings.frontend_url.rstrip('/')}/auth/complete?{urlencode({'ticket': ticket})}")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - inherited API
        return

    def _redirect_error(self, code: str) -> None:
        self._redirect(f"{settings.frontend_url.rstrip('/')}/?auth_error={code}")

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()


def _exchange_code(code: str, verifier: str) -> dict[str, Any]:
    response = httpx.post(
        settings.chatgpt_oauth_token_url,
        data={
            "grant_type": "authorization_code",
            "client_id": settings.chatgpt_oauth_client_id,
            "code": code,
            "redirect_uri": _callback_url(),
            "code_verifier": verifier,
        },
        headers={"Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _user_from_token_payload(payload: dict[str, Any]) -> AuthUser:
    claims = _decode_jwt_payload(str(payload.get("id_token") or ""))
    email = claims.get("email") or claims.get("https://api.openai.com/email")
    name = claims.get("name") or claims.get("preferred_username") or email
    sub = claims.get("sub") or email
    if not sub:
        raise ValueError("ChatGPT OAuth token did not include a subject")
    return AuthUser(sub=str(sub), email=str(email) if email else None, name=str(name) if name else None)


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _callback_url() -> str:
    return f"http://localhost:{settings.chatgpt_oauth_callback_port}/auth/callback"


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _token(bytes_count: int) -> str:
    return secrets.token_urlsafe(bytes_count).rstrip("=")


def _single(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None


def _safe_next_path(next_path: str) -> str:
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    return next_path


def _cleanup() -> None:
    now = time.time()
    for state, flow in list(_flows.items()):
        if now - flow.created_at > 600:
            _flows.pop(state, None)
    for ticket, payload in list(_tickets.items()):
        if now - payload.created_at > 120:
            _tickets.pop(ticket, None)
    for ticket, payload in list(_completed_tickets.items()):
        if now - payload.created_at > 120:
            _completed_tickets.pop(ticket, None)
