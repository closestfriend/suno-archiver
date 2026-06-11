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
