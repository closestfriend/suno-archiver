"""The Suno API adapter. Every endpoint, header, and URL lives here and only here."""

import time

import requests

STUDIO_BASE = "https://studio-api-prod.suno.com"

# Suno files every clip into exactly one workspace ("project"). The `default`
# project is only the *unassigned* bucket -- Suno labels it "Workspace for
# unassigned clips" -- so fetching it alone silently misses everything the user
# has filed into a named workspace. PROJECTS_PATH enumerates them all.
DEFAULT_PROJECT = "default"
PROJECT_PATH = "/api/project/{project}"  # 1-indexed pages
PROJECTS_PATH = "/api/project/me"  # the caller's workspaces, paginated


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

    def list_projects(self) -> list:
        """Every workspace the caller owns, as [{"id", "name", "clip_count"}].

        Paginated. Excludes nothing: the default/unassigned bucket is fetched
        separately via list_library(project="default"), and callers must
        de-duplicate by clip id because Suno also surfaces that bucket here
        under its display name ("My Workspace").
        """
        projects, page, seen = [], 1, set()
        while True:
            data = self._request("GET", f"{PROJECTS_PATH}?page={page}")
            if not isinstance(data, dict):
                raise SunoApiError(-1, "unexpected workspace response shape from Suno")
            batch = data.get("projects") or []
            if not batch:
                break
            for p in batch:
                pid = p.get("id")
                if pid and pid not in seen:
                    seen.add(pid)
                    projects.append({"id": pid, "name": p.get("name") or "untitled",
                                     "clip_count": p.get("clip_count")})
            total = data.get("num_total_results")
            if isinstance(total, int) and len(projects) >= total:
                break
            page += 1
        return projects

    def list_library(self, page: int, project: str = DEFAULT_PROJECT) -> list:
        """One page (~20 clips) of a workspace, newest first.

        `page` is 0-indexed per this method's contract; an empty list means
        past the end. The Suno endpoint is 1-indexed and nests each clip under
        project_clips[].clip, so we translate here. `project` defaults to the
        unassigned bucket; pass an id from list_projects() for a named workspace.
        """
        path = PROJECT_PATH.format(project=project)
        data = self._request("GET", f"{path}?page={page + 1}")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Known shapes: the current `project_clips` wrapper (empty list = end
            # of pagination, a legitimate result), or `clips`/`results` fallbacks.
            if "project_clips" in data:
                return [item["clip"] for item in data["project_clips"] if item.get("clip")]
            if "clips" in data or "results" in data:
                return data.get("clips") or data.get("results") or []
        # Anything else: fail loud rather than silently producing an empty archive.
        raise SunoApiError(
            -1,
            "unexpected library response shape from Suno — they may have changed "
            "their API. Run `suno-archiver doctor` or update suno-archiver.",
        )

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
