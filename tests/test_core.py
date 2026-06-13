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
    """Pages of clips; raises queued exceptions."""

    def __init__(self, pages, wav_url=None):
        self.pages = pages  # list of (list-of-clips | Exception); index = page number
        self.wav_url = wav_url
        self.wav_requests = []

    def list_library(self, page):
        if page >= len(self.pages):
            return []
        item = self.pages[page]
        if isinstance(item, Exception):
            raise item
        return item

    def request_wav(self, clip_id):
        self.wav_requests.append(clip_id)

    def get_wav_url(self, clip_id, interval=2.0, timeout=120.0):
        return self.wav_url


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

    def test_fetch_all_clips_resets_clips_on_second_call(self):
        """Calling fetch_all_clips twice must not double the clip list."""
        api = FakeApi([[clip(i) for i in range(3)]])
        a = SunoArchiver(api)
        a.fetch_all_clips()
        a.fetch_all_clips()
        self.assertEqual(len(a.clips), 3)


class TestNaming(InTempDir):
    def test_filename_base_pattern(self):
        a = SunoArchiver(FakeApi([]))
        c = clip(7, created_at="2026-06-10T05:00:00.000Z",
                 title="Skull UwU!! (on a black flag)")
        base = a.filename_base(c)
        # id is sanitized (non-alphanumerics stripped) then truncated to 8 chars:
        # "clip-0007-aaaa-bbbb" -> "clip0007". Real Suno UUIDs are unaffected
        # (their first 8 chars are hex with no separator).
        self.assertEqual(base, "2026-06-10_skull-uwu-on-a-black-flag_clip0007")

    def test_untitled_fallback(self):
        a = SunoArchiver(FakeApi([]))
        c = clip(7, title="??!!")
        self.assertIn("untitled", a.filename_base(c))


from tests.helpers import LocalServer


class TestFilenameBaseSecurity(InTempDir):
    def test_traversal_id_is_sanitized(self):
        """Fix C: id containing path separators must produce a safe base."""
        a = SunoArchiver(FakeApi([]))
        c = clip(1, created_at="2026-06-01T00:00:00.000Z")
        c["id"] = "../../../etc/passwd"
        base = a.filename_base(c)
        self.assertNotIn("/", base, "slash must not appear in filename_base")
        self.assertNotIn("..", base, "dotdot must not appear in filename_base")

    def test_traversal_id_noid_fallback(self):
        """Fix C: id that reduces to empty after sanitization falls back to 'noid'."""
        a = SunoArchiver(FakeApi([]))
        c = clip(1, created_at="2026-06-01T00:00:00.000Z")
        c["id"] = "../../../../"
        base = a.filename_base(c)
        self.assertIn("noid", base)


class TestDownloadFile(InTempDir):
    def test_non_https_url_is_refused(self):
        """Fix D: only https URLs are fetched (defense-in-depth vs SSRF)."""
        a = SunoArchiver(FakeApi([]))
        with self.assertRaises(ValueError):
            a.download_file("http://insecure.example/x.mp3", Path("."), "out")
        self.assertEqual(list(Path(".").iterdir()), [])

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

    def test_png_cover_not_redownloaded_on_second_run(self):
        """Fix A: cover served as image/png written as .png must be skipped on rerun."""
        def handler(method, path, headers, body):
            if path.endswith(".mp3"):
                return (200, {"Content-Type": "audio/mpeg"}, b"mp3bytes")
            if "/cover/" in path:
                return (200, {"Content-Type": "image/png"}, b"pngbytes")
            return (404, {"Content-Type": "text/plain"}, b"nope")
        server = LocalServer(handler)
        try:
            # image_url has no extension — server returns Content-Type image/png
            c = clip(42, created_at="2026-06-10T00:00:00.000Z",
                     audio_url=f"{server.url}/42.mp3",
                     image_url=f"{server.url}/cover/42")
            api1 = FakeApi([[c]])
            a1 = SunoArchiver(api1)
            a1.run()
            month = Path("suno_archive/2026-06")
            # First run: exactly one .png file written
            png_files = list(month.glob("*.png"))
            self.assertEqual(len(png_files), 1, "expected one .png after first run")
            self.assertEqual(a1.stats["downloaded"], 2)  # audio + cover

            # Second run with fresh archiver: must skip the png cover, not re-download
            api2 = FakeApi([[c]])
            a2 = SunoArchiver(api2)
            a2.run()
            # Still exactly one .png, not two
            png_files_after = list(month.glob("*.png"))
            self.assertEqual(len(png_files_after), 1, "must not create duplicate .png")
            self.assertEqual(a2.stats["downloaded"], 0, "nothing should be downloaded on rerun")
            self.assertEqual(a2.stats["skipped"], 2)
        finally:
            server.close()


class TestWavPath(InTempDir):
    def _server(self):
        def handler(method, path, headers, body):
            if path.endswith(".mp3"):
                return (200, {"Content-Type": "audio/mpeg"}, b"mp3bytes")
            if path.endswith(".jpeg"):
                return (200, {"Content-Type": "image/jpeg"}, b"jpgbytes")
            if path.endswith(".wav") or "wav" in path:
                return (200, {"Content-Type": "audio/wav"}, b"wavbytes")
            return (404, {"Content-Type": "text/plain"}, b"nope")
        return LocalServer(handler)

    def test_clip_with_embedded_wav_url_downloads_without_request_wav(self):
        """Clip with audio_url_wav already set: run(want_wav=True) downloads the
        wav directly; api.request_wav must NOT be called."""
        server = self._server()
        try:
            c = clip(1, created_at="2026-06-10T00:00:00.000Z",
                     audio_url=f"{server.url}/1.mp3",
                     image_url=f"{server.url}/1.jpeg",
                     audio_url_wav=f"{server.url}/1.wav")
            api = FakeApi([[c]])
            a = SunoArchiver(api, want_wav=True)
            a.run()
            month = Path("suno_archive/2026-06")
            self.assertEqual(len(list(month.glob("*.wav"))), 1)
            self.assertEqual(api.wav_requests, [])
        finally:
            server.close()

    def test_clip_without_wav_key_calls_request_wav_then_downloads(self):
        """Clip with no wav key: run(want_wav=True) must call request_wav with
        the clip id, then download from the url returned by get_wav_url."""
        server = self._server()
        try:
            c = clip(1, created_at="2026-06-10T00:00:00.000Z",
                     audio_url=f"{server.url}/1.mp3",
                     image_url=f"{server.url}/1.jpeg")
            wav_url = f"{server.url}/converted.wav"
            api = FakeApi([[c]], wav_url=wav_url)
            a = SunoArchiver(api, want_wav=True)
            a.run()
            month = Path("suno_archive/2026-06")
            self.assertEqual(len(list(month.glob("*.wav"))), 1)
            self.assertEqual(api.wav_requests, ["clip-0001-aaaa-bbbb"])
        finally:
            server.close()

    def test_clip_without_id_skips_wav_silently(self):
        """Clip with id removed and no wav keys: run(want_wav=True) must complete
        without crashing; api.wav_requests stays empty."""
        server = self._server()
        try:
            c = clip(1, created_at="2026-06-10T00:00:00.000Z",
                     audio_url=f"{server.url}/1.mp3",
                     image_url=f"{server.url}/1.jpeg")
            del c["id"]
            api = FakeApi([[c]])
            a = SunoArchiver(api, want_wav=True)
            a.run()  # must not raise
            self.assertEqual(api.wav_requests, [])
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
