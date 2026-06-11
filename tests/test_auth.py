"""Tests for suno_archiver.auth."""

import unittest
from unittest.mock import patch

from suno_archiver.auth import AuthError, get_client_cookie, cookie_candidates, build_session, _browser_cookie_candidates


class TestGetClientCookie(unittest.TestCase):
    def test_env_var_wins(self):
        with patch.dict("os.environ", {"SUNO_COOKIE": "cookie-from-env"}):
            self.assertEqual(get_client_cookie(), "cookie-from-env")

    def test_browser_extraction_fallback(self):
        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("SUNO_COOKIE", None)
            with patch("suno_archiver.auth._browser_cookie_candidates",
                       return_value=iter(["cookie-from-browser"])):
                self.assertEqual(get_client_cookie(), "cookie-from-browser")

    def test_no_cookie_anywhere_raises_with_guidance(self):
        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("SUNO_COOKIE", None)
            with patch("suno_archiver.auth._browser_cookie_candidates", return_value=iter([])):
                with self.assertRaises(AuthError) as ctx:
                    get_client_cookie()
        self.assertIn("SUNO_COOKIE", str(ctx.exception))


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

    def test_session_without_id_raises_auth_error(self):
        """Fix 1: Clerk session object missing 'id' must raise AuthError, not KeyError."""
        def handler(method, path, headers, body):
            if path.startswith("/v1/client?"):
                return json_response(200, {"response": {"sessions": [{}]}})
            return json_response(404, {"detail": "nope"})
        server = LocalServer(handler)
        try:
            s = ClerkSession("my-client-cookie", base_url=server.url)
            with self.assertRaises(AuthError) as ctx:
                s.get_token()
            self.assertIn("session", str(ctx.exception).lower())
        finally:
            server.close()


class TestGetClientCookieEdgeCases(unittest.TestCase):
    def test_empty_value_cookie_raises_auth_error(self):
        """Fix 2: __client cookie with empty value must not be returned."""
        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("SUNO_COOKIE", None)
            # _browser_cookie_candidates already filters empty values; simulate no valid ones
            with patch("suno_archiver.auth._browser_cookie_candidates", return_value=iter([])):
                with self.assertRaises(AuthError):
                    get_client_cookie()


class TestBuildSessionTriesCandidatesInOrder(unittest.TestCase):
    """build_session skips stale cookies and returns the first session that mints."""

    def _make_handler(self, stale_cookie, fresh_cookie, fresh_jwt, sessions_by_cookie):
        """Fake Clerk: stale → 401 on /v1/client; fresh → normal sid+jwt flow."""
        def handler(method, path, headers, body):
            auth = headers.get("Authorization", "")
            if path.startswith("/v1/client?"):
                if auth == fresh_cookie:
                    sid = sessions_by_cookie[fresh_cookie]
                    return json_response(200, {
                        "response": {"sessions": [{"id": sid}]}
                    })
                # stale or unknown → 401
                return json_response(401, {"detail": "invalid"})
            for cookie_val, sid in sessions_by_cookie.items():
                if path.startswith(f"/v1/client/sessions/{sid}/tokens") and auth == cookie_val:
                    return json_response(200, {"jwt": fresh_jwt})
            return json_response(404, {"detail": "nope"})
        return handler

    def test_skips_stale_returns_first_working(self):
        stale = "stale"
        fresh = "fresh"
        jwt = "jwt-fresh"
        handler = self._make_handler(stale, fresh, jwt, {fresh: "sess_fresh"})
        server = LocalServer(handler)
        try:
            with patch("suno_archiver.auth.cookie_candidates", return_value=iter([stale, fresh])):
                session = build_session(base_url=server.url)
                self.assertEqual(session.get_token(), jwt)
        finally:
            server.close()


class TestBuildSessionAllFailRaisesAuthError(unittest.TestCase):
    """build_session raises AuthError mentioning candidate count when all fail."""

    def test_all_fail_raises_with_count(self):
        def handler(method, path, headers, body):
            return json_response(401, {"detail": "invalid"})
        server = LocalServer(handler)
        try:
            with patch("suno_archiver.auth.cookie_candidates", return_value=iter(["a", "b"])):
                with self.assertRaises(AuthError) as ctx:
                    build_session(base_url=server.url)
            self.assertIn("2", str(ctx.exception))
        finally:
            server.close()


class TestBrowserCookieCandidatesDedupes(unittest.TestCase):
    """_browser_cookie_candidates dedupes and preserves browser order."""

    def _make_load_browser(self, browser_cookies):
        """Return a fake _load_browser that returns controlled cookie lists."""
        def fake_load_browser(name):
            return browser_cookies.get(name, [])
        return fake_load_browser

    def test_dedupes_preserves_order(self):
        # Chrome has cookie-A; Brave has cookie-A (dup) and cookie-B
        browser_cookies = {
            "chrome": [{"name": "__client", "value": "cookie-A", "domain": ".suno.com"}],
            "brave": [
                {"name": "__client", "value": "cookie-A", "domain": ".suno.com"},  # dup
                {"name": "__client", "value": "cookie-B", "domain": ".suno.com"},
            ],
            "firefox": [],
        }
        with patch("suno_archiver.auth._load_browser", side_effect=self._make_load_browser(browser_cookies)):
            candidates = list(_browser_cookie_candidates())
        self.assertEqual(candidates, ["cookie-A", "cookie-B"])

    def test_empty_value_skipped(self):
        browser_cookies = {
            "chrome": [{"name": "__client", "value": "", "domain": ".suno.com"}],
            "brave": [{"name": "__client", "value": "cookie-B", "domain": ".suno.com"}],
        }
        with patch("suno_archiver.auth._load_browser", side_effect=self._make_load_browser(browser_cookies)):
            candidates = list(_browser_cookie_candidates())
        self.assertEqual(candidates, ["cookie-B"])


class TestCookieCandidatesIsLazy(unittest.TestCase):
    """_browser_cookie_candidates is a generator — brave must not be called when chrome works."""

    def test_brave_never_called_when_chrome_cookie_mints(self):
        """Key laziness test: build_session stops at chrome; brave loader is never invoked."""
        from tests.helpers import LocalServer, json_response
        from suno_archiver.auth import _BROWSER_LOADER_NAMES

        called_browsers = []

        def fake_load_browser(name):
            called_browsers.append(name)
            if name == "chrome":
                return [{"name": "__client", "value": "chrome-cookie", "domain": ".suno.com"}]
            return []

        def handler(method, path, headers, body):
            if path.startswith("/v1/client?"):
                return json_response(200, {
                    "response": {"sessions": [{"id": "sess_chrome"}]}
                })
            if path.startswith("/v1/client/sessions/sess_chrome/tokens"):
                return json_response(200, {"jwt": "jwt-chrome"})
            return json_response(404, {"detail": "nope"})

        server = LocalServer(handler)
        try:
            with patch("suno_archiver.auth._load_browser", side_effect=fake_load_browser):
                import os
                os.environ.pop("SUNO_COOKIE", None)
                with patch.dict("os.environ", {}, clear=False):
                    os.environ.pop("SUNO_COOKIE", None)
                    session = build_session(base_url=server.url)
                    self.assertEqual(session.get_token(), "jwt-chrome")
            # Only chrome should have been loaded; brave and later browsers must be unvisited
            self.assertEqual(called_browsers, ["chrome"],
                             f"Expected only ['chrome'] but got {called_browsers}")
        finally:
            server.close()

    def test_browser_cookie_candidates_is_a_generator(self):
        """_browser_cookie_candidates() must return a generator, not a list."""
        import types
        with patch("suno_archiver.auth._load_browser", return_value=[]):
            result = _browser_cookie_candidates()
        self.assertIsInstance(result, types.GeneratorType)

    def test_cookie_candidates_is_a_generator_without_env(self):
        """cookie_candidates() without SUNO_COOKIE must return a generator."""
        import os
        import types
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("SUNO_COOKIE", None)
            with patch("suno_archiver.auth._load_browser", return_value=[]):
                result = cookie_candidates()
        self.assertIsInstance(result, types.GeneratorType)

    def test_cookie_candidates_with_env_is_iterable_yielding_env_value(self):
        """cookie_candidates() with SUNO_COOKIE set must yield only that value."""
        with patch.dict("os.environ", {"SUNO_COOKIE": "env-val"}):
            result = list(cookie_candidates())
        self.assertEqual(result, ["env-val"])


class TestBuildSessionNoCandidatesRaises(unittest.TestCase):
    """build_session raises AuthError mentioning SUNO_COOKIE when there are no candidates at all."""

    def test_no_candidates_raises_auth_error_mentioning_suno_cookie(self):
        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("SUNO_COOKIE", None)
            with patch("suno_archiver.auth._load_browser", return_value=[]):
                with self.assertRaises(AuthError) as ctx:
                    build_session()
        self.assertIn("SUNO_COOKIE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
