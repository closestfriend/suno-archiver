"""Tests for suno_archiver.suno_api."""

import json
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

    def test_non_json_2xx_raises_status_minus_one(self):
        """Non-JSON 2xx must raise SunoApiError with status==-1 and 'non-JSON' in message."""
        def handler(method, path, headers, body):
            return (200, {"Content-Type": "text/html"}, b"<html>login</html>")
        server = LocalServer(handler)
        try:
            api = SunoApi(FakeSession(), base_url=server.url)
            with self.assertRaises(SunoApiError) as ctx:
                api.list_library(page=0)
            self.assertEqual(ctx.exception.status, -1)
            self.assertIn("non-JSON", str(ctx.exception))
        finally:
            server.close()


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

    def test_wav_poll_at_least_once_with_timeout_zero(self):
        """get_wav_url(timeout=0) must poll once and return URL if immediately available."""
        def handler(method, path, headers, body):
            return json_response(200, {"wav_file_url": "https://cdn.example/x.wav"})
        server = LocalServer(handler)
        try:
            api = SunoApi(FakeSession(), base_url=server.url)
            url = api.get_wav_url("clip123", interval=0.01, timeout=0)
            self.assertEqual(url, "https://cdn.example/x.wav")
        finally:
            server.close()


class TestLibraryEndpoint(unittest.TestCase):
    def test_uses_project_default_with_1indexed_pages_and_unwraps_project_clips(self):
        seen_paths = []
        def handler(method, path, headers, body):
            seen_paths.append(path)
            return json_response(200, {
                "project_clips": [
                    {"clip": {"id": "a", "title": "One"}, "pinned": False, "relative_index": 0.0},
                    {"clip": {"id": "b", "title": "Two"}, "pinned": False, "relative_index": 1.0},
                ],
                "clip_count": 1668,
            })
        server = LocalServer(handler)
        try:
            api = SunoApi(FakeSession(), base_url=server.url)
            clips = api.list_library(page=0)   # core's 0-indexed page 0
            self.assertEqual([c["id"] for c in clips], ["a", "b"])  # unwrapped
            self.assertEqual(seen_paths[0], "/api/project/default?page=1")  # 1-indexed
        finally:
            server.close()

    def test_empty_project_clips_means_end(self):
        def handler(method, path, headers, body):
            return json_response(200, {"project_clips": [], "clip_count": 1668})
        server = LocalServer(handler)
        try:
            api = SunoApi(FakeSession(), base_url=server.url)
            self.assertEqual(api.list_library(page=99), [])
        finally:
            server.close()

    def test_clips_or_results_fallback_shapes_still_work(self):
        for key in ("clips", "results"):
            def handler(method, path, headers, body, _k=key):
                return json_response(200, {_k: [{"id": "x"}]})
            server = LocalServer(handler)
            try:
                api = SunoApi(FakeSession(), base_url=server.url)
                self.assertEqual(api.list_library(page=0), [{"id": "x"}], key)
            finally:
                server.close()

    def test_unrecognized_shape_fails_loud_not_silent_empty(self):
        """Fix B: an unknown response shape must raise (diagnosable), not silently
        return [] and produce an empty archive."""
        def handler(method, path, headers, body):
            return json_response(200, {"songs": [{"id": "x"}], "total": 1})
        server = LocalServer(handler)
        try:
            api = SunoApi(FakeSession(), base_url=server.url)
            with self.assertRaises(SunoApiError) as ctx:
                api.list_library(page=0)
            self.assertIn("shape", str(ctx.exception).lower())
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
