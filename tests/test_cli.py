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
