"""The Suno API adapter. Every endpoint, header, and URL lives here and only here."""

import time

import requests

STUDIO_BASE = "https://studio-api.prod.suno.com"
FEED_PATH = "/api/feed/v2"  # verified against real account in live-verification task; /api/feed/ is the fallback
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
