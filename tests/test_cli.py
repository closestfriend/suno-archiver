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
        self.assertIn("1.0.1", result.output)

    def test_archive_invokes_core_and_exits_nonzero_on_total_failure(self):
        fake = MagicMock()
        fake.clips = []
        fake.fetch_complete = False
        with patch("suno_archiver.cli._build_archiver", return_value=fake):
            result = CliRunner().invoke(main, [])
        fake.run.assert_called_once()
        self.assertEqual(result.exit_code, 1)

    def test_last_run_conflicts_with_until(self):
        result = CliRunner().invoke(main, ["--last-run", "--until", "2026-01-01"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("--last-run", result.output)


class TestDoctor(unittest.TestCase):
    def test_doctor_happy_path(self):
        from suno_archiver.suno_api import SunoApi
        api = MagicMock(spec=SunoApi)
        api.list_library.return_value = [{"id": "a"}, {"id": "b"}]
        with patch("suno_archiver.cli.cookie_candidates", return_value=iter(["cookie"])), \
             patch("suno_archiver.cli.build_session", return_value=MagicMock()), \
             patch("suno_archiver.cli.SunoApi", return_value=api):
            result = CliRunner().invoke(main, ["doctor"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("All good", result.output)

    def test_doctor_fails_when_no_cookie(self):
        with patch("suno_archiver.cli.cookie_candidates", return_value=iter([])):
            result = CliRunner().invoke(main, ["doctor"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("FAIL", result.output)

    def test_doctor_fails_when_token_mint_fails(self):
        from suno_archiver.auth import AuthError
        with patch("suno_archiver.cli.cookie_candidates", return_value=iter(["cookie"])), \
             patch("suno_archiver.cli.build_session", side_effect=AuthError("expired")):
            result = CliRunner().invoke(main, ["doctor"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("FAIL", result.output)

    def test_doctor_fails_when_library_fetch_fails(self):
        from suno_archiver.suno_api import SunoApi, SunoApiError
        api = MagicMock(spec=SunoApi)
        api.list_library.side_effect = SunoApiError(500, "boom")
        with patch("suno_archiver.cli.cookie_candidates", return_value=iter(["cookie"])), \
             patch("suno_archiver.cli.build_session", return_value=MagicMock()), \
             patch("suno_archiver.cli.SunoApi", return_value=api):
            result = CliRunner().invoke(main, ["doctor"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("changed their API", result.output)


if __name__ == "__main__":
    unittest.main()
