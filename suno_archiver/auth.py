"""Cookie acquisition and Clerk JWT lifecycle for Suno."""

import os
import time

import requests

CLERK_BASE = "https://auth.suno.com"
CLERK_API_VERSION = "2025-11-10"
CLERK_JS_VERSION = "5.117.0"
TOKEN_MAX_AGE_SECONDS = 30


class AuthError(Exception):
    """Authentication problem with a user-actionable message."""


def _browser_cookies():
    """Load suno.com cookies from installed browsers via rookiepy."""
    import rookiepy  # imported lazily: optional at runtime if SUNO_COOKIE is set

    try:
        return rookiepy.load(["suno.com"])
    except Exception:
        return []


def get_client_cookie() -> str:
    """Find the Suno Clerk __client cookie: SUNO_COOKIE env var, then browsers."""
    env_cookie = os.getenv("SUNO_COOKIE")
    if env_cookie:
        return env_cookie

    for cookie in _browser_cookies():
        if cookie.get("name") == "__client":
            return cookie.get("value", "")

    raise AuthError(
        "No Suno session found. Either log into suno.com in your browser, "
        "or set SUNO_COOKIE to your __client cookie value (see README)."
    )


class ClerkSession:
    """Mints and caches short-lived Suno JWTs from the long-lived __client cookie."""

    def __init__(self, client_cookie: str, base_url: str = CLERK_BASE):
        self.client_cookie = client_cookie
        self.base_url = base_url
        self._session_id = None
        self._token = None
        self._token_minted_at = 0.0

    def _clerk_params(self) -> str:
        return f"__clerk_api_version={CLERK_API_VERSION}&_clerk_js_version={CLERK_JS_VERSION}"

    def _get_session_id(self) -> str:
        if self._session_id:
            return self._session_id
        resp = requests.get(
            f"{self.base_url}/v1/client?{self._clerk_params()}",
            headers={"Authorization": self.client_cookie},
            timeout=30,
        )
        if not resp.ok:
            raise AuthError(
                f"Suno session rejected (HTTP {resp.status_code}). "
                "Log into suno.com in your browser and re-run, or update SUNO_COOKIE."
            )
        sessions = (resp.json().get("response") or {}).get("sessions") or []
        if not sessions:
            raise AuthError("No active Suno session for this cookie. Log into suno.com and re-run.")
        self._session_id = sessions[0]["id"]
        return self._session_id

    def get_token(self) -> str:
        age = time.time() - self._token_minted_at
        if self._token and age < TOKEN_MAX_AGE_SECONDS:
            return self._token
        sid = self._get_session_id()
        resp = requests.post(
            f"{self.base_url}/v1/client/sessions/{sid}/tokens?{self._clerk_params()}",
            headers={"Authorization": self.client_cookie},
            timeout=30,
        )
        if not resp.ok:
            raise AuthError(
                f"Could not refresh Suno token (HTTP {resp.status_code}). "
                "Log into suno.com in your browser and re-run."
            )
        self._token = resp.json().get("jwt")
        if not self._token:
            raise AuthError("Clerk returned no JWT; Suno may have changed auth. Run `suno-archiver doctor`.")
        self._token_minted_at = time.time()
        return self._token

    def invalidate(self) -> None:
        self._token = None
        self._token_minted_at = 0.0
