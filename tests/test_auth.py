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


if __name__ == "__main__":
    unittest.main()
