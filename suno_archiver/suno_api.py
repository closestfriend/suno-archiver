"""The Suno API adapter. Every endpoint, header, and URL lives here and only here."""

import time

import requests

STUDIO_BASE = "https://studio-api.prod.suno.com"
LIBRARY_PATH = "/api/project/default"  # the owned "My Workspace" default project (1-indexed pages)


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
            raise SunoApiError(-1, f"non-JSON response from Suno (HTTP {resp.status_code})")

    def list_library(self, page: int) -> list:
        """One page (~20 clips) of the user's library, newest first.

        `page` is 0-indexed per this method's contract; an empty list means
        past the end. The Suno endpoint is 1-indexed and nests each clip under
        project_clips[].clip, so we translate here.
        """
        data = self._request("GET", f"{LIBRARY_PATH}?page={page + 1}")
        if isinstance(data, dict) and "project_clips" in data:
            return [item["clip"] for item in data["project_clips"] if item.get("clip")]
        if isinstance(data, dict):
            return data.get("clips") or data.get("results") or []
        return data or []

    def request_wav(self, clip_id: str) -> None:
        self._request("POST", f"/api/gen/{clip_id}/convert_wav/")

    def get_wav_url(self, clip_id: str, interval: float = 2.0, timeout: float = 120.0) -> str:
        deadline = time.time() + timeout
        while True:
            data = self._request("GET", f"/api/gen/{clip_id}/wav_file/")
            if isinstance(data, dict):
                for key in ("wav_file_url", "audio_url_wav", "wav_url", "audio_url"):
                    if data.get(key):
                        return data[key]
            if time.time() >= deadline:
                raise SunoApiError(408, f"WAV conversion for {clip_id} not ready after {timeout:.0f}s")
            time.sleep(interval)
