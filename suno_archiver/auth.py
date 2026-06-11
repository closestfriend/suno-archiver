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
