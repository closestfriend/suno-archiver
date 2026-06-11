# suno-archiver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PyPI-published CLI (`suno-archiver`) that archives a Suno user's own library — MP3s, optional WAVs, cover art, complete metadata — with full and incremental (`--last-run`) modes.

**Architecture:** Four modules with one isolation boundary: `auth.py` (cookie + Clerk JWT lifecycle), `suno_api.py` (ALL Suno endpoint knowledge; raises `SunoApiError`), `core.py` (fetch → filter → 4-worker download pool → state, porting the proven replicate-predictions-downloader-py invariants), `cli.py` (Click). Tests use local `ThreadingHTTPServer` fakes for Clerk and the studio API — zero live calls.

**Tech Stack:** Python ≥3.9, requests, click, python-dotenv, rookiepy, hatchling, stdlib unittest.

**Working directory for all commands:** `/Volumes/2025_exSSD_2tb/🔮 AI Outputs & Generations/suno-archiver`

**Spec:** `docs/superpowers/specs/2026-06-11-suno-archiver-design.md`

---

### Task 0: Project scaffold

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `suno_archiver/__init__.py`, `tests/__init__.py`, `README.md` (stub)

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "suno-archiver"
version = "1.0.0"
description = "Archive your Suno music library: audio, cover art, and complete metadata, with incremental sync"
readme = "README.md"
license = "MIT"
authors = [
    { name = "Hunter Shokrian", email = "hnshokrian@gmail.com" }
]
keywords = ["suno", "ai-music", "downloader", "backup", "archive", "cli", "music-generation"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Console",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Topic :: Multimedia :: Sound/Audio",
]
requires-python = ">=3.9"
dependencies = [
    "requests>=2.28.0",
    "click>=8.0.0",
    "python-dotenv>=1.0.0",
    "rookiepy>=0.5.0",
]

[project.scripts]
suno-archiver = "suno_archiver.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["suno_archiver"]
```

- [ ] **Step 2: Create .gitignore**

```
.env
.env.*
.venv/
__pycache__/
*.py[cod]
dist/
build/
*.egg-info/
suno_archive*/
.suno-archiver-state.json
.DS_Store
```

- [ ] **Step 3: Create suno_archiver/__init__.py**

```python
"""Suno Archiver - back up your Suno music library."""

__version__ = "1.0.0"
```

- [ ] **Step 4: Create empty `tests/__init__.py` and a one-line `README.md`**

README.md content (expanded in Task 12):

```markdown
# suno-archiver

Archive your Suno music library: audio, cover art, and complete metadata.
```

- [ ] **Step 5: Create venv and install deps**

Run: `python3 -m venv .venv && .venv/bin/pip install -q requests click python-dotenv rookiepy`
Expected: exit 0

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "Scaffold suno-archiver package"
```

---

### Task 1: Test helper — local fake server

**Files:**
- Create: `tests/helpers.py`

Test infrastructure (no TDD cycle for the helper itself; it gets exercised by every later test).

- [ ] **Step 1: Write tests/helpers.py**

```python
"""Shared test helpers: a tiny threaded HTTP server with per-test handlers."""

import http.server
import json
import threading


class LocalServer:
    """handler(method, path, headers, body) -> (status, headers_dict, body_bytes)."""

    def __init__(self, handler):
        outer_handler = handler

        class Handler(http.server.BaseHTTPRequestHandler):
            def _respond(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                status, headers, out = outer_handler(
                    self.command, self.path, dict(self.headers), body
                )
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            do_GET = _respond
            do_POST = _respond

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def json_response(status, payload):
    return (status, {"Content-Type": "application/json"}, json.dumps(payload).encode())
```

- [ ] **Step 2: Commit**

```bash
git add tests/ && git commit -m "Add LocalServer test helper"
```

---

### Task 2: auth.get_client_cookie — env var first, rookiepy fallback

**Files:**
- Create: `suno_archiver/auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for suno_archiver.auth."""

import unittest
from unittest.mock import patch

from suno_archiver.auth import AuthError, get_client_cookie


class TestGetClientCookie(unittest.TestCase):
    def test_env_var_wins(self):
        with patch.dict("os.environ", {"SUNO_COOKIE": "cookie-from-env"}):
            self.assertEqual(get_client_cookie(), "cookie-from-env")

    def test_browser_extraction_fallback(self):
        fake_cookies = [
            {"name": "other", "value": "x", "domain": ".suno.com"},
            {"name": "__client", "value": "cookie-from-browser", "domain": ".suno.com"},
        ]
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("SUNO_COOKIE", None)
            with patch("suno_archiver.auth._browser_cookies", return_value=fake_cookies):
                self.assertEqual(get_client_cookie(), "cookie-from-browser")

    def test_no_cookie_anywhere_raises_with_guidance(self):
        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("SUNO_COOKIE", None)
            with patch("suno_archiver.auth._browser_cookies", return_value=[]):
                with self.assertRaises(AuthError) as ctx:
                    get_client_cookie()
        self.assertIn("SUNO_COOKIE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_auth -v`
Expected: FAIL/ERROR — `cannot import name 'get_client_cookie'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_auth -v`
Expected: 3 tests, OK

- [ ] **Step 5: Commit**

```bash
git add suno_archiver/auth.py tests/test_auth.py && git commit -m "auth: cookie acquisition (env var, browser fallback)"
```

---

### Task 3: ClerkSession — JWT minting, caching, invalidation

**Files:**
- Modify: `suno_archiver/auth.py` (append class)
- Test: `tests/test_auth.py` (append)

- [ ] **Step 1: Append failing tests to tests/test_auth.py**

```python
from tests.helpers import LocalServer, json_response
from suno_archiver.auth import ClerkSession


class TestClerkSession(unittest.TestCase):
    def _fake_clerk(self, mint_counter):
        def handler(method, path, headers, body):
            if path.startswith("/v1/client?"):
                assert headers.get("Authorization") == "my-client-cookie"
                return json_response(200, {
                    "response": {"sessions": [{"id": "sess_123"}]}
                })
            if path.startswith("/v1/client/sessions/sess_123/tokens"):
                mint_counter.append(1)
                return json_response(200, {"jwt": f"jwt-{len(mint_counter)}"})
            return json_response(404, {"detail": "nope"})
        return handler

    def test_mints_and_caches_token(self):
        mints = []
        server = LocalServer(self._fake_clerk(mints))
        try:
            s = ClerkSession("my-client-cookie", base_url=server.url)
            self.assertEqual(s.get_token(), "jwt-1")
            self.assertEqual(s.get_token(), "jwt-1")  # cached, no second mint
            self.assertEqual(len(mints), 1)
        finally:
            server.close()

    def test_invalidate_forces_fresh_mint(self):
        mints = []
        server = LocalServer(self._fake_clerk(mints))
        try:
            s = ClerkSession("my-client-cookie", base_url=server.url)
            self.assertEqual(s.get_token(), "jwt-1")
            s.invalidate()
            self.assertEqual(s.get_token(), "jwt-2")
        finally:
            server.close()

    def test_bad_cookie_raises_auth_error(self):
        def handler(method, path, headers, body):
            return json_response(401, {"detail": "invalid"})
        server = LocalServer(handler)
        try:
            s = ClerkSession("bad-cookie", base_url=server.url)
            with self.assertRaises(AuthError):
                s.get_token()
        finally:
            server.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_auth -v`
Expected: ERROR — `cannot import name 'ClerkSession'`

- [ ] **Step 3: Append implementation to suno_archiver/auth.py**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_auth -v`
Expected: 6 tests, OK

- [ ] **Step 5: Commit**

```bash
git add suno_archiver/auth.py tests/test_auth.py && git commit -m "auth: ClerkSession JWT minting with caching and invalidation"
```

---

### Task 4: SunoApi adapter — request core with 401 re-mint-and-retry

**Files:**
- Create: `suno_archiver/suno_api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for suno_archiver.suno_api."""

import unittest

from tests.helpers import LocalServer, json_response
from suno_archiver.suno_api import SunoApi, SunoApiError


class FakeSession:
    """Stands in for ClerkSession: serves tokens, records invalidations."""

    def __init__(self):
        self.tokens = ["token-1", "token-2"]
        self.served = 0
        self.invalidations = 0

    def get_token(self):
        token = self.tokens[min(self.served, len(self.tokens) - 1)]
        self.served += 1
        return token

    def invalidate(self):
        self.invalidations += 1


class TestRequestCore(unittest.TestCase):
    def test_sends_bearer_token(self):
        seen = {}
        def handler(method, path, headers, body):
            seen["auth"] = headers.get("Authorization")
            return json_response(200, [])
        server = LocalServer(handler)
        try:
            api = SunoApi(FakeSession(), base_url=server.url)
            api.list_library(page=0)
            self.assertEqual(seen["auth"], "Bearer token-1")
        finally:
            server.close()

    def test_401_triggers_one_remint_and_retry(self):
        calls = []
        def handler(method, path, headers, body):
            calls.append(headers.get("Authorization"))
            if len(calls) == 1:
                return json_response(401, {"detail": "expired"})
            return json_response(200, [])
        server = LocalServer(handler)
        try:
            session = FakeSession()
            api = SunoApi(session, base_url=server.url)
            api.list_library(page=0)
            self.assertEqual(calls, ["Bearer token-1", "Bearer token-2"])
            self.assertEqual(session.invalidations, 1)
        finally:
            server.close()

    def test_persistent_error_raises_suno_api_error(self):
        def handler(method, path, headers, body):
            return json_response(500, {"detail": "server exploded"})
        server = LocalServer(handler)
        try:
            api = SunoApi(FakeSession(), base_url=server.url)
            with self.assertRaises(SunoApiError) as ctx:
                api.list_library(page=0)
            self.assertEqual(ctx.exception.status, 500)
            self.assertIn("server exploded", str(ctx.exception))
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_api -v`
Expected: ERROR — `No module named 'suno_archiver.suno_api'`

- [ ] **Step 3: Write the implementation**

```python
"""The Suno API adapter. Every endpoint, header, and URL lives here and only here."""

import time

import requests

STUDIO_BASE = "https://studio-api.prod.suno.com"
FEED_PATH = "/api/feed/v2"  # verified against real account in Task 11; /api/feed/ is the fallback
FEED_FILTERS = "hide_disliked=true&hide_gen_stems=true&hide_studio_clips=true"


class SunoApiError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail
        super().__init__(f"Suno API error {status}: {detail}")


class SunoApi:
    def __init__(self, session, base_url: str = STUDIO_BASE):
        self.session = session  # ClerkSession-compatible: get_token() / invalidate()
        self.base_url = base_url

    def _request(self, method: str, path: str, _retried: bool = False):
        resp = requests.request(
            method,
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.session.get_token()}"},
            timeout=60,
        )
        if resp.status_code == 401 and not _retried:
            self.session.invalidate()
            return self._request(method, path, _retried=True)
        if not resp.ok:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise SunoApiError(resp.status_code, detail)
        try:
            return resp.json()
        except ValueError:
            raise SunoApiError(resp.status_code, "response was not JSON")

    def list_library(self, page: int) -> list:
        """One page of the user's library, newest first. Empty list = past the end."""
        data = self._request("GET", f"{FEED_PATH}?page={page}&{FEED_FILTERS}")
        if isinstance(data, dict):  # some deployments wrap: {"clips": [...]}
            return data.get("clips") or data.get("results") or []
        return data or []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_api -v`
Expected: 3 tests, OK

- [ ] **Step 5: Commit**

```bash
git add suno_archiver/suno_api.py tests/test_api.py && git commit -m "api: request core with Bearer auth and 401 re-mint-retry"
```

---

### Task 5: SunoApi WAV — request conversion, poll for URL

**Files:**
- Modify: `suno_archiver/suno_api.py` (append methods)
- Test: `tests/test_api.py` (append)

- [ ] **Step 1: Append failing tests to tests/test_api.py**

```python
class TestWav(unittest.TestCase):
    def test_wav_poll_resolves_when_ready(self):
        polls = []
        def handler(method, path, headers, body):
            if path.endswith("/convert_wav/") and method == "POST":
                return json_response(200, {})
            if path.endswith("/wav_file/"):
                polls.append(1)
                if len(polls) < 3:
                    return json_response(200, {})  # not ready: no URL yet
                return json_response(200, {"wav_file_url": "https://cdn.example/x.wav"})
            return json_response(404, {"detail": "nope"})
        server = LocalServer(handler)
        try:
            api = SunoApi(FakeSession(), base_url=server.url)
            api.request_wav("clip123")
            url = api.get_wav_url("clip123", interval=0.01, timeout=5)
            self.assertEqual(url, "https://cdn.example/x.wav")
            self.assertEqual(len(polls), 3)
        finally:
            server.close()

    def test_wav_poll_times_out(self):
        def handler(method, path, headers, body):
            return json_response(200, {})  # never ready
        server = LocalServer(handler)
        try:
            api = SunoApi(FakeSession(), base_url=server.url)
            with self.assertRaises(SunoApiError) as ctx:
                api.get_wav_url("clip123", interval=0.01, timeout=0.05)
            self.assertIn("WAV", str(ctx.exception))
        finally:
            server.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_api -v`
Expected: ERROR — `'SunoApi' object has no attribute 'request_wav'`

- [ ] **Step 3: Append implementation to suno_archiver/suno_api.py**

```python
    def request_wav(self, clip_id: str) -> None:
        self._request("POST", f"/api/gen/{clip_id}/convert_wav/")

    def get_wav_url(self, clip_id: str, interval: float = 2.0, timeout: float = 120.0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self._request("GET", f"/api/gen/{clip_id}/wav_file/")
            if isinstance(data, dict):
                for key in ("wav_file_url", "audio_url_wav", "wav_url", "audio_url"):
                    if data.get(key):
                        return data[key]
            time.sleep(interval)
        raise SunoApiError(408, f"WAV conversion for {clip_id} not ready after {timeout:.0f}s")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_api -v`
Expected: 5 tests, OK

- [ ] **Step 5: Commit**

```bash
git add suno_archiver/suno_api.py tests/test_api.py && git commit -m "api: WAV conversion request and polling"
```

---

### Task 6: core date parsing and state (the timezone lessons, ported)

**Files:**
- Create: `suno_archiver/core.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for suno_archiver.core."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from suno_archiver.core import SunoArchiver


class FakeApi:
    """Pages of clips; raises queued exceptions; serves wav urls."""

    def __init__(self, pages):
        self.pages = pages  # list of (list-of-clips | Exception); index = page number

    def list_library(self, page):
        if page >= len(self.pages):
            return []
        item = self.pages[page]
        if isinstance(item, Exception):
            raise item
        return item


def clip(i, created_at="2026-06-01T00:00:00.000Z", **over):
    base = {
        "id": f"clip-{i:04d}-aaaa-bbbb",
        "title": f"Test Song {i}",
        "audio_url": None,
        "image_url": None,
        "display_name": "closestfriend",
        "created_at": created_at,
        "metadata": {"prompt": "synthwave test", "tags": "synthwave", "lyrics": "la la"},
    }
    base.update(over)
    return base


class InTempDir(unittest.TestCase):
    def setUp(self):
        self._old = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._old)
        self._tmp.cleanup()


class TestDates(InTempDir):
    def test_relative_dates_are_aware_utc(self):
        a = SunoArchiver(FakeApi([]))
        parsed = a.parse_date("2 hours ago")
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset(), timedelta(0))
        expected = datetime.now(timezone.utc) - timedelta(hours=2)
        self.assertLess(abs((parsed - expected).total_seconds()), 5)

    def test_plain_and_iso_dates_are_aware_utc(self):
        a = SunoArchiver(FakeApi([]))
        for text in ("2026-01-15", "2026-01-15T10:30:00Z", "yesterday"):
            parsed = a.parse_date(text)
            self.assertEqual(parsed.utcoffset(), timedelta(0), text)

    def test_garbage_dates_raise(self):
        a = SunoArchiver(FakeApi([]))
        with self.assertRaises(ValueError):
            a.parse_date("not a date")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_core -v`
Expected: ERROR — `No module named 'suno_archiver.core'`

- [ ] **Step 3: Write suno_archiver/core.py (first slice)**

```python
"""Orchestration: fetch -> filter -> download pool -> state."""

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from .suno_api import SunoApiError

STATE_FILENAME = ".suno-archiver-state.json"
DOWNLOAD_CONCURRENCY = 4


class SunoArchiver:
    def __init__(self, api, archive_dir="suno_archive", since=None, until=None,
                 last_run=False, want_wav=False):
        self.api = api
        self.archive_dir = Path(archive_dir)
        self.since = self.parse_date(since) if since else None
        self.until = self.parse_date(until) if until else None
        self.last_run = last_run
        self.want_wav = want_wav
        self.clips = []
        self.fetch_complete = False
        self.fetch_start_time = None

    # ---- dates (timezone-aware UTC everywhere; naive local time corrupts watermarks)

    def parse_date(self, date_str):
        if not date_str:
            return None
        date_str = str(date_str).strip().lower()
        now = datetime.now(timezone.utc)
        if date_str == "yesterday":
            return now - timedelta(days=1)
        match = re.match(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s+ago", date_str)
        if match:
            amount, unit = int(match.group(1)), match.group(2)
            deltas = {
                "minute": timedelta(minutes=amount),
                "hour": timedelta(hours=amount),
                "day": timedelta(days=amount),
                "week": timedelta(weeks=amount),
                "month": timedelta(days=amount * 30),
                "year": timedelta(days=amount * 365),
            }
            return now - deltas[unit]
        try:
            parsed = datetime.fromisoformat(date_str.replace("z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            raise ValueError(
                f'Invalid date: "{date_str}". Use "2026-01-15", '
                '"2026-01-15T10:30:00Z", or "2 days ago".'
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_core -v`
Expected: 3 tests, OK

- [ ] **Step 5: Commit**

```bash
git add suno_archiver/core.py tests/test_core.py && git commit -m "core: timezone-aware date parsing"
```

---

### Task 7: core fetch — pagination, filters, fetch_complete

**Files:**
- Modify: `suno_archiver/core.py` (append methods)
- Test: `tests/test_core.py` (append)

- [ ] **Step 1: Append failing tests to tests/test_core.py**

```python
class TestFetch(InTempDir):
    def test_fetches_all_pages(self):
        api = FakeApi([[clip(i) for i in range(20)], [clip(i) for i in range(20, 30)]])
        a = SunoArchiver(api)
        a.fetch_all_clips()
        self.assertEqual(len(a.clips), 30)
        self.assertTrue(a.fetch_complete)
        self.assertIsNotNone(a.fetch_start_time)

    def test_since_filter_early_stops(self):
        page0 = [clip(1, created_at="2026-06-10T00:00:00.000Z"),
                 clip(2, created_at="2026-01-01T00:00:00.000Z")]
        page1 = Exception("must never fetch page 1")
        a = SunoArchiver(FakeApi([page0, page1]), since="2026-03-01")
        a.fetch_all_clips()
        self.assertEqual([c["id"] for c in a.clips], ["clip-0001-aaaa-bbbb"])
        self.assertTrue(a.fetch_complete)

    def test_until_filter_skips_newer(self):
        page0 = [clip(1, created_at="2026-06-10T00:00:00.000Z"),
                 clip(2, created_at="2026-02-01T00:00:00.000Z")]
        a = SunoArchiver(FakeApi([page0]), until="2026-03-01")
        a.fetch_all_clips()
        self.assertEqual([c["id"] for c in a.clips], ["clip-0002-aaaa-bbbb"])

    def test_error_mid_fetch_marks_incomplete_but_keeps_partial(self):
        from suno_archiver.suno_api import SunoApiError
        api = FakeApi([[clip(1)], SunoApiError(500, "boom")])
        a = SunoArchiver(api)
        a.fetch_all_clips()  # must not raise
        self.assertEqual(len(a.clips), 1)
        self.assertFalse(a.fetch_complete)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_core -v`
Expected: ERROR — `'SunoArchiver' object has no attribute 'fetch_all_clips'`

- [ ] **Step 3: Append implementation to core.py**

```python
    # ---- fetch

    def _clip_created_at(self, c):
        raw = c.get("created_at")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _resolve_since(self):
        if not self.last_run:
            return self.since
        state = self.load_state()
        raw = state.get("last_successful_run")
        if not raw:
            print("No previous run found; archiving everything.")
            return self.since
        since = datetime.fromisoformat(raw)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        print(f"Archiving clips created since last run: {since.isoformat()}")
        return since

    def fetch_all_clips(self):
        since = self._resolve_since()
        # Watermark = fetch start: anything created later is the next run's job.
        self.fetch_start_time = datetime.now(timezone.utc).isoformat()
        self.fetch_complete = False
        page = 0
        past_since = False
        try:
            while True:
                clips = self.api.list_library(page)
                if not clips:
                    break
                print(f"Fetched page {page + 1}: {len(clips)} clips")
                for c in clips:
                    created = self._clip_created_at(c)
                    if since and created and created < since:
                        past_since = True  # results are newest-first
                        break
                    if self.until and created and created > self.until:
                        continue
                    self.clips.append(c)
                if past_since:
                    break
                page += 1
            self.fetch_complete = True
        except SunoApiError as e:
            print(f"Error fetching page {page + 1}: {e}")
            print("Fetch incomplete; continuing with what was retrieved. "
                  "Last-run state will NOT be saved.")
        print(f"Total clips fetched: {len(self.clips)}")

    # ---- state

    def _state_path(self):
        return self.archive_dir / STATE_FILENAME

    def load_state(self):
        try:
            return json.loads(self._state_path().read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def save_state(self, state):
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._state_path().write_text(json.dumps(state, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_core -v`
Expected: 7 tests, OK

- [ ] **Step 5: Commit**

```bash
git add suno_archiver/core.py tests/test_core.py && git commit -m "core: paginated fetch with date filters and fetch_complete tracking"
```

---

### Task 8: core filenames and download — sanitize, extensions, hardened fetch

**Files:**
- Modify: `suno_archiver/core.py` (append methods)
- Test: `tests/test_core.py` (append)

- [ ] **Step 1: Append failing tests to tests/test_core.py**

```python
from tests.helpers import LocalServer


class TestNaming(InTempDir):
    def test_filename_base_pattern(self):
        a = SunoArchiver(FakeApi([]))
        c = clip(7, created_at="2026-06-10T05:00:00.000Z",
                 title="Skull UwU!! (on a black flag)")
        base = a.filename_base(c)
        self.assertEqual(base, "2026-06-10_skull-uwu-on-a-black-flag_clip-000")

    def test_untitled_fallback(self):
        a = SunoArchiver(FakeApi([]))
        c = clip(7, title="??!!")
        self.assertIn("untitled", a.filename_base(c))


class TestDownloadFile(InTempDir):
    def test_http_error_raises_and_leaves_no_file(self):
        def handler(method, path, headers, body):
            return (404, {"Content-Type": "text/plain"}, b"gone")
        server = LocalServer(handler)
        try:
            a = SunoArchiver(FakeApi([]))
            with self.assertRaises(Exception):
                a.download_file(f"{server.url}/x.mp3", Path("."), "out")
            self.assertEqual(list(Path(".").iterdir()), [])
        finally:
            server.close()

    def test_content_type_fallback_for_extensionless_url(self):
        def handler(method, path, headers, body):
            return (200, {"Content-Type": "audio/mpeg"}, b"mp3bytes")
        server = LocalServer(handler)
        try:
            a = SunoArchiver(FakeApi([]))
            filepath, size = a.download_file(f"{server.url}/cdn/abc123", Path("."), "out")
            self.assertTrue(str(filepath).endswith("out.mp3"))
            self.assertEqual(size, 8)
        finally:
            server.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_core -v`
Expected: ERROR — `'SunoArchiver' object has no attribute 'filename_base'`

- [ ] **Step 3: Append implementation to core.py**

```python
    # ---- naming and downloads

    def _sanitize(self, name, max_length=50):
        s = re.sub(r"[^a-zA-Z0-9\- ]", "", str(name or ""))
        s = re.sub(r"\s+", "-", s.strip()).lower().strip("-")
        return s[:max_length] or "untitled"

    def filename_base(self, c):
        created = self._clip_created_at(c)
        date_str = created.strftime("%Y-%m-%d") if created else "unknown-date"
        return f"{date_str}_{self._sanitize(c.get('title'))}_{str(c.get('id'))[:8]}"

    def _month_dir(self, c):
        created = self._clip_created_at(c)
        bucket = created.strftime("%Y-%m") if created else "unknown-date"
        return self.archive_dir / bucket

    def _extension_for(self, url, content_type):
        path_ext = Path(urlparse(url).path).suffix.lower()
        if path_ext and re.fullmatch(r"\.[a-z0-9]{1,5}", path_ext) and re.search(r"[a-z]", path_ext):
            return path_ext
        if content_type:
            subtype = content_type.split(";")[0].strip().split("/")[-1].lower()
            special = {"mpeg": ".mp3", "jpeg": ".jpg", "plain": ".txt",
                       "svg+xml": ".svg", "octet-stream": None}
            if subtype in special:
                return special[subtype] or ".bin"
            if re.fullmatch(r"[a-z0-9]{1,5}", subtype):
                return f".{subtype}"
        return ".bin"

    def download_file(self, url, directory, base_name):
        """Raises on HTTP errors; deletes partial files; returns (path, bytes)."""
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        ext = self._extension_for(url, resp.headers.get("Content-Type"))
        directory.mkdir(parents=True, exist_ok=True)
        filepath = directory / f"{base_name}{ext}"
        size = 0
        try:
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    size += len(chunk)
        except Exception:
            filepath.unlink(missing_ok=True)
            raise
        return filepath, size
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_core -v`
Expected: 11 tests, OK

- [ ] **Step 5: Commit**

```bash
git add suno_archiver/core.py tests/test_core.py && git commit -m "core: filenames, month buckets, hardened downloads"
```

---

### Task 9: core run() — jobs, pool, metadata, index, state guard, idempotency

**Files:**
- Modify: `suno_archiver/core.py` (append methods)
- Test: `tests/test_core.py` (append)

- [ ] **Step 1: Append failing tests to tests/test_core.py**

```python
class TestRun(InTempDir):
    def _server(self):
        def handler(method, path, headers, body):
            if path.endswith(".mp3"):
                return (200, {"Content-Type": "audio/mpeg"}, b"mp3bytes")
            if path.endswith(".jpeg"):
                return (200, {"Content-Type": "image/jpeg"}, b"jpgbytes")
            return (404, {"Content-Type": "text/plain"}, b"nope")
        return LocalServer(handler)

    def _clips(self, url, n=3):
        return [clip(i, created_at="2026-06-10T00:00:00.000Z",
                     audio_url=f"{url}/{i}.mp3", image_url=f"{url}/{i}.jpeg")
                for i in range(n)]

    def test_run_downloads_audio_covers_metadata_and_index(self):
        server = self._server()
        try:
            a = SunoArchiver(FakeApi([self._clips(server.url)]))
            a.run()
            month = Path("suno_archive/2026-06")
            self.assertEqual(len(list(month.glob("*.mp3"))), 3)
            self.assertEqual(len(list(month.glob("*.jpg"))), 3)
            self.assertEqual(len(list(month.glob("*.json"))), 3)
            index = json.loads(Path("suno_archive/library_index.json").read_text())
            self.assertEqual(index["total_clips"], 3)
            self.assertEqual(len(index["clips"]), 3)
            state = json.loads(Path("suno_archive/.suno-archiver-state.json").read_text())
            self.assertEqual(state["last_successful_run"], a.fetch_start_time)
        finally:
            server.close()

    def test_rerun_skips_existing_files(self):
        server = self._server()
        try:
            a1 = SunoArchiver(FakeApi([self._clips(server.url)]))
            a1.run()
            first_stats = a1.stats["downloaded"]
            a2 = SunoArchiver(FakeApi([self._clips(server.url)]))
            a2.run()
            self.assertEqual(first_stats, 6)  # 3 mp3 + 3 covers
            self.assertEqual(a2.stats["downloaded"], 0)
            self.assertEqual(a2.stats["skipped"], 6)
        finally:
            server.close()

    def test_incomplete_fetch_saves_no_state(self):
        from suno_archiver.suno_api import SunoApiError
        server = self._server()
        try:
            api = FakeApi([self._clips(server.url), SunoApiError(500, "boom")])
            a = SunoArchiver(api)
            a.run()
            self.assertFalse(Path("suno_archive/.suno-archiver-state.json").exists())
        finally:
            server.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_core -v`
Expected: ERROR — `'SunoArchiver' object has no attribute 'run'`

- [ ] **Step 3: Append implementation to core.py**

```python
    # ---- orchestration

    def _wav_url_in_clip(self, c):
        for key in ("audio_url_wav", "wav_url", "wav_audio_url", "master_wav_url"):
            if c.get(key):
                return c[key]
        return None

    def _build_jobs(self):
        """Returns (jobs, skipped). One job per file to fetch; writes per-clip JSON."""
        jobs, skipped = [], 0
        for c in self.clips:
            month = self._month_dir(c)
            base = self.filename_base(c)
            month.mkdir(parents=True, exist_ok=True)
            (month / f"{base}.json").write_text(json.dumps(c, indent=2, default=str))

            def queue(url, suffix_hint):
                nonlocal skipped
                existing = list(month.glob(f"{base}{suffix_hint}"))
                if existing:
                    skipped += 1
                elif url:
                    jobs.append((url, month, base))

            queue(c.get("audio_url"), ".mp3")
            queue(c.get("image_url"), ".jp*g")
            if self.want_wav:
                wav = self._wav_url_in_clip(c)
                if list(month.glob(f"{base}.wav")):
                    skipped += 1
                elif wav:
                    jobs.append((wav, month, base))
                else:
                    jobs.append(("__convert__:" + str(c.get("id")), month, base))
        return jobs, skipped

    def _run_job(self, job):
        url, directory, base = job
        if url.startswith("__convert__:"):
            clip_id = url.split(":", 1)[1]
            self.api.request_wav(clip_id)
            url = self.api.get_wav_url(clip_id)
        return self.download_file(url, directory, base)

    def _write_index(self):
        index = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_clips": len(self.clips),
            "clips": self.clips,
        }
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        (self.archive_dir / "library_index.json").write_text(
            json.dumps(index, indent=2, default=str))

    def run(self):
        self.stats = {"downloaded": 0, "skipped": 0, "errors": 0, "bytes": 0}
        self.fetch_all_clips()
        if not self.clips:
            if not self.fetch_complete:
                print("Could not fetch your library — see the error above.")
                import sys
                sys.exit(1) if False else None  # exit handled by CLI via return code
            else:
                print("No clips matched.")
            return

        self._write_index()
        jobs, self.stats["skipped"] = self._build_jobs()
        print(f"Downloading {len(jobs)} files "
              f"({self.stats['skipped']} already archived) "
              f"with concurrency {DOWNLOAD_CONCURRENCY}...")

        lock = threading.Lock()
        done = [0]

        def work(job):
            try:
                filepath, size = self._run_job(job)
                with lock:
                    done[0] += 1
                    self.stats["downloaded"] += 1
                    self.stats["bytes"] += size
                    print(f"  [{done[0]}/{len(jobs)}] ok {filepath.name}")
            except Exception as e:
                with lock:
                    done[0] += 1
                    self.stats["errors"] += 1
                    print(f"  [{done[0]}/{len(jobs)}] FAILED {job[0][:80]}: {e}")

        if jobs:
            with ThreadPoolExecutor(max_workers=DOWNLOAD_CONCURRENCY) as pool:
                list(pool.map(work, jobs))

        print(f"\nDone. {self.stats['downloaded']} downloaded, "
              f"{self.stats['skipped']} skipped, {self.stats['errors']} errors, "
              f"{self.stats['bytes'] / 1e6:.1f} MB")

        if self.fetch_complete:
            self.save_state({
                "last_successful_run": self.fetch_start_time,
                "total_clips": len(self.clips),
            })
            print("State saved for incremental runs (--last-run).")
        else:
            print("Fetch was incomplete — last-run state NOT updated. Re-run to retry.")
```

Note: remove the dead `sys.exit` line shown above — the empty-and-incomplete case simply
returns; the CLI checks `archiver.fetch_complete` and `archiver.clips` to set the exit code.
Final version of that block:

```python
        if not self.clips:
            if not self.fetch_complete:
                print("Could not fetch your library — see the error above.")
            else:
                print("No clips matched.")
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_core -v`
Expected: 14 tests, OK

- [ ] **Step 5: Run the FULL suite**

Run: `.venv/bin/python -m unittest discover -v`
Expected: all tests across test_auth/test_api/test_core, OK

- [ ] **Step 6: Commit**

```bash
git add suno_archiver/core.py tests/test_core.py && git commit -m "core: run() with job pool, index, idempotent re-runs, state guard"
```

---

### Task 10: CLI — flags, mutual exclusion, doctor

**Files:**
- Create: `suno_archiver/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the CLI (uses click's test runner; no network)."""

import unittest
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from suno_archiver.cli import main


class TestCli(unittest.TestCase):
    def test_last_run_conflicts_with_since(self):
        result = CliRunner().invoke(main, ["--last-run", "--since", "yesterday"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("--last-run", result.output)

    def test_version_flag(self):
        result = CliRunner().invoke(main, ["--version"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("1.0.0", result.output)

    def test_archive_invokes_core_and_exits_nonzero_on_total_failure(self):
        fake = MagicMock()
        fake.clips = []
        fake.fetch_complete = False
        with patch("suno_archiver.cli._build_archiver", return_value=fake):
            result = CliRunner().invoke(main, [])
        fake.run.assert_called_once()
        self.assertEqual(result.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_cli -v`
Expected: ERROR — `No module named 'suno_archiver.cli'`

- [ ] **Step 3: Write suno_archiver/cli.py**

```python
"""Command-line interface."""

import sys

import click
from dotenv import load_dotenv

from . import __version__
from .auth import AuthError, ClerkSession, get_client_cookie
from .core import SunoArchiver
from .suno_api import SunoApi, SunoApiError


def _build_archiver(**kwargs):
    cookie = get_client_cookie()
    api = SunoApi(ClerkSession(cookie))
    return SunoArchiver(api, **kwargs)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="suno-archiver")
@click.option("-s", "--since", help='Archive clips created since ("2026-01-15", "2 weeks ago")')
@click.option("-u", "--until", help="Archive clips created until this date")
@click.option("-l", "--last-run", is_flag=True, help="Incremental: only clips since the last successful run")
@click.option("--wav", is_flag=True, help="Also fetch WAVs (slow: requests conversion per song)")
@click.option("--dir", "archive_dir", default="suno_archive", show_default=True,
              help="Archive root directory")
@click.pass_context
def main(ctx, since, until, last_run, wav, archive_dir):
    """Archive your Suno library: audio, cover art, and complete metadata."""
    load_dotenv()
    if ctx.invoked_subcommand is not None:
        return
    if last_run and (since or until):
        raise click.UsageError("--last-run cannot be combined with --since/--until")
    try:
        archiver = _build_archiver(archive_dir=archive_dir, since=since,
                                   until=until, last_run=last_run, want_wav=wav)
        archiver.run()
        if not archiver.clips and not archiver.fetch_complete:
            sys.exit(1)
    except (AuthError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
def doctor():
    """Diagnose auth and API health step by step."""
    load_dotenv()
    click.echo("1. Looking for Suno session cookie...")
    try:
        cookie = get_client_cookie()
        click.echo("   ok: cookie found")
    except AuthError as e:
        click.echo(f"   FAIL: {e}")
        sys.exit(1)

    click.echo("2. Exchanging cookie for a token (Clerk)...")
    session = ClerkSession(cookie)
    try:
        session.get_token()
        click.echo("   ok: token minted")
    except AuthError as e:
        click.echo(f"   FAIL: {e}")
        click.echo("   Your session may be expired: log into suno.com and retry.")
        sys.exit(1)

    click.echo("3. Fetching library page 1...")
    api = SunoApi(session)
    try:
        clips = api.list_library(page=0)
        click.echo(f"   ok: {len(clips)} clips on page 1")
    except SunoApiError as e:
        click.echo(f"   FAIL: {e}")
        click.echo("   Auth works but the feed endpoint failed — Suno may have "
                   "changed their API. Check for a newer suno-archiver release.")
        sys.exit(1)

    click.echo("\nAll good. You're ready to run: suno-archiver")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_cli -v`
Expected: 3 tests, OK

- [ ] **Step 5: Run full suite + smoke the CLI**

Run: `.venv/bin/python -m unittest discover && .venv/bin/pip install -q -e . && .venv/bin/suno-archiver --version && .venv/bin/suno-archiver --help`
Expected: all tests OK; version prints 1.0.0; help shows all flags + doctor command

- [ ] **Step 6: Commit**

```bash
git add suno_archiver/cli.py tests/test_cli.py && git commit -m "cli: archive command, flag validation, doctor"
```

---

### Task 11: LIVE verification against Hunter's real account (manual gate)

**Files:** possibly modify `suno_archiver/suno_api.py` (FEED_PATH) — nothing else.

This task resolves the spec's open question (`/api/feed/v2` vs `/api/feed/`) and
must be run by/with Hunter since it needs his real browser session.

- [ ] **Step 1: Run doctor with the real session**

Run (Hunter logged into suno.com in his browser):
`cd "/Volumes/2025_exSSD_2tb/🔮 AI Outputs & Generations/suno-archiver" && .venv/bin/suno-archiver doctor`
Expected: all three checks `ok`. If step 3 fails with 404/422: edit
`suno_archiver/suno_api.py`, change `FEED_PATH = "/api/feed/v2"` to `"/api/feed/"`,
re-run doctor.

- [ ] **Step 2: Verify the feed returns HIS library (not the public feed)**

Run: `.venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv()
from suno_archiver.auth import ClerkSession, get_client_cookie
from suno_archiver.suno_api import SunoApi
api = SunoApi(ClerkSession(get_client_cookie()))
clips = api.list_library(0)
print(len(clips), 'clips; first titles:', [c.get('title') for c in clips[:5]])
print('display names:', {c.get('display_name') for c in clips[:10]})
"`
Expected: titles Hunter recognizes as his own; display_name = his handle.
If these are strangers' songs, the endpoint is the public feed — switch FEED_PATH
as in Step 1 and re-verify.

- [ ] **Step 3: Small live archive run**

Run: `mkdir -p /tmp/suno-live-test && cd /tmp/suno-live-test && "/Volumes/2025_exSSD_2tb/🔮 AI Outputs & Generations/suno-archiver/.venv/bin/suno-archiver" --since "1 week ago"`
Expected: month folder with MP3s + covers + per-clip JSON, `library_index.json`,
state file written. Listen to one MP3 to confirm it's real audio.

- [ ] **Step 4: Live --wav spot check**

Run: `cd /tmp/suno-live-test && "/Volumes/2025_exSSD_2tb/🔮 AI Outputs & Generations/suno-archiver/.venv/bin/suno-archiver" --since "2 days ago" --wav`
Expected: `.wav` files appear next to MP3s (conversion + poll may take ~1-2 min per new song).

- [ ] **Step 5: Live --last-run check**

Run: `cd /tmp/suno-live-test && "/Volumes/2025_exSSD_2tb/🔮 AI Outputs & Generations/suno-archiver/.venv/bin/suno-archiver" --last-run`
Expected: "0 files" (or only clips created since Step 3), exit 0.

- [ ] **Step 6: Commit any endpoint fix**

```bash
git add -A && git commit -m "Verify endpoints against live account" --allow-empty
```

---

### Task 12: README, posture, and final hygiene

**Files:**
- Modify: `README.md` (full rewrite)
- Create: `LICENSE`, `CHANGELOG.md`, `.env.example`

- [ ] **Step 1: Write the full README.md**

```markdown
# suno-archiver

Archive your [Suno](https://suno.com) music library to local disk: MP3s,
optional WAVs, cover art, and complete metadata (prompts, style tags, lyrics,
dates) — with one-shot full archives and incremental sync.

## Why

Your library is yours, but it lives on someone else's servers under terms that
can change overnight (early 2026: free-tier downloads were removed entirely
after Suno's Warner Music deal). Keep local copies.

## Important: what this is and isn't

- Personal backup of **your own** creations, on an account entitled to
  download them (audio downloads require a paid Suno plan).
- Built on Suno's **undocumented** web API. It can break whenever Suno changes
  things. If something fails, run `suno-archiver doctor` first, then check for
  a newer release.

## Install

    pipx install suno-archiver    # or: pip install suno-archiver

## Auth

Just be logged into suno.com in your browser — the tool finds your session
cookie automatically (Chrome, Firefox, Safari, Arc, ...).

Headless/manual alternative: copy the `__client` cookie from DevTools
(Application → Cookies → suno.com) into a `.env` file:

    SUNO_COOKIE=eyJhbGc...

## Usage

    suno-archiver                      # full archive: MP3s + covers + metadata
    suno-archiver --wav                # also WAVs (slower: conversion per song)
    suno-archiver --last-run           # only what's new since the last run
    suno-archiver --since "2 weeks ago"
    suno-archiver --dir ~/Music/suno_archive
    suno-archiver doctor               # diagnose auth/API issues

## What lands on disk

    suno_archive/
    ├── 2026-06/
    │   ├── 2026-06-10_my-song-title_a1b2c3d4.mp3
    │   ├── 2026-06-10_my-song-title_a1b2c3d4.jpg     (cover art)
    │   └── 2026-06-10_my-song-title_a1b2c3d4.json    (full metadata)
    ├── library_index.json    (everything, searchable with jq/grep)
    └── .suno-archiver-state.json

Re-runs are idempotent: existing files are skipped, so `--last-run` on a
schedule keeps the archive current.

## Related

- [replicate-predictions-downloader](https://github.com/closestfriend/replicate-predictions-downloader) — same philosophy for Replicate (npm + PyPI)

## License

MIT
```

- [ ] **Step 2: Create LICENSE (MIT, copyright 2026 Hunter Shokrian), CHANGELOG.md (1.0.0 entry: initial release, feature list from README), and .env.example (`SUNO_COOKIE=your_client_cookie_here`)**

- [ ] **Step 3: Full suite + build check**

Run: `.venv/bin/python -m unittest discover && .venv/bin/pip install -q build twine && .venv/bin/python -m build && .venv/bin/python -m twine check dist/*`
Expected: tests OK; both artifacts PASSED

- [ ] **Step 4: Commit and tag**

```bash
git add -A && git commit -m "Docs, license, changelog for 1.0.0" && git tag v1.0.0
```

---

### Task 13: Ship

- [ ] **Step 1: Create GitHub repo and push**

```bash
cd "/Volumes/2025_exSSD_2tb/🔮 AI Outputs & Generations/suno-archiver"
gh repo create closestfriend/suno-archiver --public --source=. --push --description "Archive your Suno music library: audio, cover art, and complete metadata"
git push --tags
```

- [ ] **Step 2: PyPI publish (Hunter runs; needs his token)**

```bash
.venv/bin/python -m twine upload dist/*
```

- [ ] **Step 3: Verify the registry**

Run: `curl -s https://pypi.org/pypi/suno-archiver/json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['info']['version'], d['info']['author'])"`
Expected: `1.0.0 Hunter Shokrian`

---

## Self-Review (completed)

- **Spec coverage:** auth (Tasks 2-3), adapter+WAV (4-5), dates/state/fetch (6-7),
  naming/downloads (8), orchestration/index/idempotency (9), CLI+doctor (10),
  live endpoint verification — the spec's flagged open question (11), posture/README (12), ship (13). ✓
- **Placeholder scan:** no TBDs; every code step has complete code. ✓
- **Type consistency:** `ClerkSession.get_token()/invalidate()` used by `SunoApi`
  and faked identically in tests; `SunoArchiver(api, archive_dir=, since=, until=,
  last_run=, want_wav=)` consistent across Tasks 6-10; `download_file` returns
  `(Path, int)` everywhere; `stats` dict keys consistent between Task 9 code and tests. ✓
```
