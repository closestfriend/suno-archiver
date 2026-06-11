"""Cookie acquisition and Clerk JWT lifecycle for Suno."""

import os
import time

import requests

CLERK_BASE = "https://auth.suno.com"
CLERK_API_VERSION = "2025-11-10"
CLERK_JS_VERSION = "5.117.0"
TOKEN_MAX_AGE_SECONDS = 30

_BROWSER_LOADER_NAMES = (
    "chrome", "brave", "firefox", "edge", "safari",
    "arc", "opera", "vivaldi", "chromium",
)

_AUTH_ERROR_MESSAGE = (
    "No Suno session found. Either log into suno.com in your browser, "
    "or set SUNO_COOKIE to your __client cookie value (see README)."
)


class AuthError(Exception):
    """Authentication problem with a user-actionable message."""


def _browser_cookies():
    """Load suno.com cookies from installed browsers via rookiepy (legacy helper)."""
    import rookiepy  # imported lazily: optional at runtime if SUNO_COOKIE is set

    try:
        return rookiepy.load(["suno.com"])
    except Exception:
        return []


def _load_browser(name: str) -> list:
    """Load suno.com cookies from a single named browser via rookiepy.

    Returns a list of cookie dicts, or [] if the browser is not installed or
    the read fails.  Separated from _browser_cookie_candidates so tests can
    patch it cheaply.
    """
    try:
        import rookiepy
    except ImportError:
        return []
    fn = getattr(rookiepy, name, None)
    if fn is None:
        return []
    try:
        return fn(["suno.com"])
    except Exception:
        return []


def _browser_cookie_candidates() -> list[str]:
    """Collect __client cookie VALUES from every readable browser.

    Iterates explicit per-browser loaders, collects non-empty __client values
    preserving browser order, and dedupes while preserving order.
    Returns [] if rookiepy is not installed or no cookies are found.
    """
    seen: set[str] = set()
    result: list[str] = []
    for name in _BROWSER_LOADER_NAMES:
        for cookie in _load_browser(name):
            if cookie.get("name") == "__client":
                value = cookie.get("value", "")
                if value and value not in seen:
                    seen.add(value)
                    result.append(value)
    return result


def cookie_candidates() -> list[str]:
    """Return ordered list of __client cookie candidates to try.

    If SUNO_COOKIE env var is set, returns [that value].
    Otherwise, collects from all readable browsers via _browser_cookie_candidates().
    Raises AuthError if no candidates are found.
    """
    env_cookie = os.getenv("SUNO_COOKIE")
    if env_cookie:
        return [env_cookie]
    candidates = _browser_cookie_candidates()
    if not candidates:
        raise AuthError(_AUTH_ERROR_MESSAGE)
    return candidates


def build_session(base_url: str = CLERK_BASE) -> "ClerkSession":
    """Try each cookie candidate until one successfully mints a Clerk JWT.

    Returns the first ClerkSession whose .get_token() succeeds.
    Raises AuthError if all candidates fail.
    """
    candidates = cookie_candidates()
    for candidate in candidates:
        session = ClerkSession(candidate, base_url=base_url)
        try:
            session.get_token()
            return session
        except AuthError:
            continue
    n = len(candidates)
    raise AuthError(
        f"Found {n} Suno session cookie(s) but none could start a session. "
        "Log into suno.com in your browser and re-run."
    )


def get_client_cookie() -> str:
    """Find the Suno Clerk __client cookie: SUNO_COOKIE env var, then browsers.

    Backward-compatible: returns cookie_candidates()[0].
    """
    return cookie_candidates()[0]


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
        session_id = sessions[0].get("id")
        if not session_id:
            raise AuthError(
                "Clerk returned a session with no ID; Suno may have changed auth. "
                "Run `suno-archiver doctor`."
            )
        self._session_id = session_id
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
