from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

import requests

TIDAL_AUTHORIZATION_URL = "https://login.tidal.com/authorize"
TIDAL_TOKEN_URL = "https://auth.tidal.com/v1/oauth2/token"
TIDAL_KEYRING_SERVICE = "pylrcget.tidal"
TIDAL_DEFAULT_SCOPES = ("user.read",)


class TidalAuthenticationError(RuntimeError):
    """Raised when TIDAL OAuth cannot produce a usable access token."""


class TidalTokenStore(Protocol):
    def load(self, client_id: str) -> dict[str, Any] | None:
        ...

    def save(self, client_id: str, token: dict[str, Any]) -> None:
        ...

    def delete(self, client_id: str) -> None:
        ...


class KeyringTidalTokenStore:
    """Store OAuth tokens in the platform keyring instead of application DB."""

    def __init__(self, *, service_name: str = TIDAL_KEYRING_SERVICE) -> None:
        self.service_name = service_name

    def load(self, client_id: str) -> dict[str, Any] | None:
        try:
            import keyring

            value = keyring.get_password(self.service_name, client_id)
        except Exception as exc:
            raise TidalAuthenticationError(f"Could not access the system keyring: {exc}") from exc
        if not value:
            return None
        try:
            token = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TidalAuthenticationError("Stored TIDAL credentials are invalid") from exc
        if not isinstance(token, dict):
            raise TidalAuthenticationError("Stored TIDAL credentials are invalid")
        return token

    def save(self, client_id: str, token: dict[str, Any]) -> None:
        try:
            import keyring

            keyring.set_password(
                self.service_name,
                client_id,
                json.dumps(token, ensure_ascii=True, separators=(",", ":")),
            )
        except Exception as exc:
            raise TidalAuthenticationError(f"Could not save TIDAL credentials securely: {exc}") from exc

    def delete(self, client_id: str) -> None:
        try:
            import keyring

            keyring.delete_password(self.service_name, client_id)
        except Exception as exc:
            # Keyring backends commonly report a missing credential as an error.
            if "not found" not in str(exc).casefold() and "no password" not in str(exc).casefold():
                raise TidalAuthenticationError(f"Could not remove TIDAL credentials: {exc}") from exc


@dataclass(frozen=True, slots=True)
class TidalAccessContext:
    """OAuth access data passed to TIDAL clients without exposing credentials to UI code."""

    access_token: str
    country_code: str | None = None
    expires_at: float | None = None


class TidalSessionProvider(Protocol):
    """Authentication/session boundary for official TIDAL API access."""

    def is_connected(self) -> bool:
        ...

    def connect(self) -> None:
        ...

    def disconnect(self) -> None:
        ...

    def get_access_context(self) -> TidalAccessContext:
        ...


class TidalOAuthSession:
    """Small OAuth 2.1 + PKCE session for the official TIDAL API."""

    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        *,
        scopes: tuple[str, ...] = TIDAL_DEFAULT_SCOPES,
        token_store: TidalTokenStore | None = None,
        http_session: requests.Session | None = None,
        open_browser: Callable[[str], bool] = webbrowser.open,
        authorization_timeout_s: float = 300.0,
    ) -> None:
        self.client_id = str(client_id).strip()
        self.redirect_uri = str(redirect_uri).strip()
        self.scopes = tuple(str(scope).strip() for scope in scopes if str(scope).strip())
        self.token_store = token_store or KeyringTidalTokenStore()
        self.http_session = http_session or requests.Session()
        self.open_browser = open_browser
        self.authorization_timeout_s = max(1.0, float(authorization_timeout_s))
        self._lock = threading.RLock()

    def is_connected(self) -> bool:
        try:
            self.get_access_context()
        except TidalAuthenticationError:
            return False
        return True

    def connect(self) -> None:
        with self._lock:
            self._validate_configuration()
            token = self.token_store.load(self.client_id)
            if token is not None:
                try:
                    self._context_from_token(token)
                    return
                except TidalAuthenticationError:
                    if not token.get("refresh_token"):
                        self.token_store.delete(self.client_id)
                    else:
                        refreshed = self._refresh(token["refresh_token"])
                        self.token_store.save(self.client_id, refreshed)
                        return
            token = self._authorize_with_pkce()
            self.token_store.save(self.client_id, token)

    def disconnect(self) -> None:
        self._validate_configuration()
        self.token_store.delete(self.client_id)

    def get_access_context(self) -> TidalAccessContext:
        with self._lock:
            self._validate_configuration()
            token = self.token_store.load(self.client_id)
            if token is None:
                raise TidalAuthenticationError("TIDAL is not connected")
            try:
                return self._context_from_token(token)
            except TidalAuthenticationError:
                refresh_token = token.get("refresh_token")
                if not refresh_token:
                    raise
                refreshed = self._refresh(str(refresh_token))
                self.token_store.save(self.client_id, refreshed)
                return self._context_from_token(refreshed)

    def _validate_configuration(self) -> None:
        if not self.client_id:
            raise TidalAuthenticationError("TIDAL client ID is not configured")
        parsed = urllib.parse.urlparse(self.redirect_uri)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise TidalAuthenticationError("TIDAL redirect URI must use a localhost HTTP callback")
        if not parsed.port:
            raise TidalAuthenticationError("TIDAL redirect URI must include a callback port")

    def _context_from_token(self, token: dict[str, Any]) -> TidalAccessContext:
        access_token = str(token.get("access_token") or "").strip()
        if not access_token:
            raise TidalAuthenticationError("TIDAL access token is missing")
        expires_at = _token_expiry(token)
        if expires_at is not None and expires_at <= time.time() + 60:
            raise TidalAuthenticationError("TIDAL access token expired")
        return TidalAccessContext(access_token=access_token, expires_at=expires_at)

    def _authorize_with_pkce(self) -> dict[str, Any]:
        parsed = urllib.parse.urlparse(self.redirect_uri)
        callback = _OAuthCallbackServer(parsed.hostname or "127.0.0.1", parsed.port or 0)
        verifier = _code_verifier()
        challenge = _code_challenge(verifier)
        state = secrets.token_urlsafe(32)
        callback.start()
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": " ".join(self.scopes),
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "state": state,
            }
        )
        try:
            if not self.open_browser(f"{TIDAL_AUTHORIZATION_URL}?{query}"):
                raise TidalAuthenticationError("Could not open the TIDAL login page")
            result = callback.wait(self.authorization_timeout_s)
        finally:
            callback.close()
        if result.get("state") != state:
            raise TidalAuthenticationError("TIDAL OAuth state validation failed")
        if result.get("error"):
            detail = result.get("error_description") or result["error"]
            raise TidalAuthenticationError(f"TIDAL authorization failed: {detail}")
        code = result.get("code")
        if not code:
            raise TidalAuthenticationError("TIDAL authorization callback did not contain a code")
        return self._exchange_code(str(code), verifier)

    def _exchange_code(self, code: str, verifier: str) -> dict[str, Any]:
        response = self.http_session.post(
            TIDAL_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": verifier,
            },
            timeout=15,
        )
        return _parse_token_response(response)

    def _refresh(self, refresh_token: str) -> dict[str, Any]:
        response = self.http_session.post(
            TIDAL_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
        token = _parse_token_response(response)
        token.setdefault("refresh_token", refresh_token)
        return token


class _OAuthCallbackServer:
    def __init__(self, host: str, port: int) -> None:
        self._result: dict[str, str] | None = None
        self._event = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                owner._result = {key: values[-1] for key, values in query.items() if values}
                owner._event.set()
                body = b"TIDAL authorization received. You can return to PyLrcGet."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def wait(self, timeout_s: float) -> dict[str, str]:
        if not self._event.wait(timeout_s):
            raise TidalAuthenticationError("Timed out waiting for the TIDAL authorization callback")
        return self._result or {}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)


def _parse_token_response(response: requests.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        detail = (response.text or "")[:300]
        raise TidalAuthenticationError(
            f"TIDAL token request failed ({response.status_code}): {detail or 'HTTP error'}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise TidalAuthenticationError("TIDAL token response was not valid JSON") from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise TidalAuthenticationError("TIDAL token response did not contain an access token")
    token = dict(payload)
    token["expires_at"] = time.time() + float(token.get("expires_in") or 0)
    return token


def _token_expiry(token: dict[str, Any]) -> float | None:
    try:
        if token.get("expires_at") is not None:
            return float(token["expires_at"])
        if token.get("expires_in") is not None:
            return time.time() + float(token["expires_in"])
    except (TypeError, ValueError):
        return None
    return None


def _code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
