"""Orchestration: fetch -> filter -> download pool -> state."""

import base64
import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
import time

import requests
from Crypto.Cipher import AES
from Crypto.Util import Counter

from .suno_api import SunoApiError

STATE_FILENAME = ".suno-archiver-state.json"
DOWNLOAD_CONCURRENCY = 8
WAIT_BETWEEN_WORKSPACES = 1.0  # seconds to wait between workspaces to avoid Suno rate-limit errors

M4A_API_BASE = "https://studio-api-prod.suno.com"
MANGO_CHUNK_SIZE = 256 * 1024  # 256 KB Chunks für Mango DRM Decryption

# Folder for Suno's default project (its unassigned-clips bucket). Leading
# underscore sorts it apart from real workspace names.
UNASSIGNED_DIRNAME = "_unassigned"
# Sort floor for clips with no parseable created_at, so index ordering is total.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# Key added to each clip recording which workspace it came from. Not a Suno
# field -- we set it so the on-disk JSON and library_index stay queryable.
WORKSPACE_KEY = "workspace"

# Primary-audio extensions (the audio_url download). WAV is a SEPARATE deliverable
# with its own `.wav` skip check, so it's deliberately excluded here — a stray .wav
# must not suppress re-downloading a missing MP3.
AUDIO_EXTS = ("mp3", "m4a", "ogg", "opus", "flac", "aac")
IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "gif")


class SunoArchiver:
    def __init__(self, api, archive_dir="suno_archive", since=None, until=None,
                 last_run=False, want_wav=False, want_m4a=False, want_art=True, only_workspaces=None):
        self.api = api
        self.archive_dir = Path(archive_dir)
        self.since = self.parse_date(since) if since else None
        self.until = self.parse_date(until) if until else None
        self.last_run = last_run
        self.want_wav = want_wav
        self.want_m4a = want_m4a
        self.want_art = want_art
        self.only_workspaces = list(only_workspaces or [])
        self.clips = []
        self.fetch_complete = False
        self.workspaces_complete = True
        self.fetch_start_time = None

    # ---- dates (timezone-aware UTC everywhere; naive local time corrupts watermarks)

    def parse_date(self, date_str):
        if not date_str:
            return None
        date_str = str(date_str).strip().lower()
        now = datetime.now(timezone.utc)
        if date_str == "yesterday":
            return now - timedelta(days=1)
        match = re.match(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s+ago", date_str)
        if match:
            amount, unit = int(match.group(1)), match.group(2)
            deltas = {
                "minute": timedelta(minutes=amount),
                "hour": timedelta(hours=amount),
                "day": timedelta(days=amount),
                "week": timedelta(weeks=amount),
                "month": timedelta(days=amount * 30),
                "year": timedelta(days=amount * 365),
            }
            return now - deltas[unit]
        try:
            parsed = datetime.fromisoformat(date_str.replace("z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            raise ValueError(
                f'Invalid date: "{date_str}". Use "2026-01-15", '
                '"2026-01-15T10:30:00Z", or "2 days ago".'
            )

    # ---- fetch

    def _clip_created_at(self, c):
        raw = c.get("created_at")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _resolve_since(self):
        if not self.last_run:
            return self.since
        state = self.load_state()
        raw = state.get("last_successful_run")
        if not raw:
            print("No previous run found; archiving everything.")
            return self.since
        since = datetime.fromisoformat(raw)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        print(f"Archiving clips created since last run: {since.isoformat()}")
        return since

    def _workspaces(self):
        """[(project_id, folder_name)] -- unassigned bucket first, then named.

        A failure to enumerate must not reduce us to archiving nothing, so we
        fall back to the unassigned bucket alone and report the run incomplete.
        """
        default = (None, UNASSIGNED_DIRNAME)
        try:
            projects = self.api.list_projects()
        except SunoApiError as e:
            print(f"WARNING: could not list workspaces ({e}).")
            print("Falling back to the unassigned bucket only — this run will be "
                  "INCOMPLETE and last-run state will NOT be saved.")
            self.workspaces_complete = False
            return [default]
        self.workspaces_complete = True
        found = [default] + [(p["id"], p["name"]) for p in projects]
        if not self.only_workspaces:
            print(f"Found {len(projects)} workspace(s) plus the unassigned bucket.")
            return found
        return self._select(found)

    def _select(self, found):
        """Narrow to --workspace picks, matching on name or on-disk folder name.

        An unmatched pick is an error, not an empty archive: silently
        archiving nothing is the exact failure mode this tool already had once.
        """
        def keys(label):
            return {label.casefold(), self._workspace_dirname(label).casefold()}

        wanted = [w.strip() for w in self.only_workspaces if w.strip()]
        chosen, unmatched = [], []
        for want in wanted:
            matches = [ws for ws in found if want.casefold() in keys(ws[1])]
            if matches:
                chosen.extend(m for m in matches if m not in chosen)
            else:
                unmatched.append(want)
        if unmatched:
            available = ", ".join(sorted(label for _, label in found))
            raise ValueError(
                f"no such workspace: {', '.join(repr(u) for u in unmatched)}. "
                f"Available: {available}"
            )
        print(f"Archiving {len(chosen)} selected workspace(s): "
              f"{', '.join(label for _, label in chosen)}")
        return chosen

    def _fetch_workspace(self, project_id, label, since, seen):
        """Clips from one workspace, newest-first, honoring since/until.

        `seen` is the run-wide set of clip ids: Suno lists the unassigned bucket
        a second time under its display name, and a clip could in principle sit
        in two workspaces, so first workspace to yield a clip owns it.

        Clips are appended to self.clips as each page arrives, so an error
        partway through keeps everything already retrieved.
        """
        kept, page, past_since = 0, 0, False
        print(f"workspace: {label}")
        while True:
            kwargs = {} if project_id is None else {"project": project_id}
            clips = self.api.list_library(page, **kwargs)
            #print(f"clips: {clips}")
            if not clips:
                break
            for c in clips:
                created = self._clip_created_at(c)
                if since and created and created < since:
                    past_since = True  # results are newest-first
                    break
                if self.until and created and created > self.until:
                    continue
                cid = c.get("id")
                if cid and cid in seen:
                    continue
                if cid:
                    seen.add(cid)
                c[WORKSPACE_KEY] = label
                self.clips.append(c)
                kept += 1
            if past_since:
                break
            page += 1
        return kept

    def fetch_all_clips(self):
        self.clips = []
        since = self._resolve_since()
        # Watermark = fetch start: anything created later is the next run's job.
        self.fetch_start_time = datetime.now(timezone.utc).isoformat()
        self.fetch_complete = False
        self.workspaces_complete = True
        seen = set()
        workspaces = self._workspaces()
        try:
            first = True
            for project_id, label in workspaces:
                if not first:
                    time.sleep(WAIT_BETWEEN_WORKSPACES)  # avoid Suno rate-limit errors
                first = False
                kept = self._fetch_workspace(project_id, label, since, seen)
                if kept:
                    print(f"  {label}: {kept} clips")
            self.fetch_complete = self.workspaces_complete
        except SunoApiError as e:
            print(f"Error fetching workspace clips: {e}")
            print("Fetch incomplete; continuing with what was retrieved. "
                  "Last-run state will NOT be saved.")
        print(f"Total clips fetched: {len(self.clips)}")

    # ---- state

    def _state_path(self):
        return self.archive_dir / STATE_FILENAME

    def load_state(self):
        try:
            return json.loads(self._state_path().read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def save_state(self, state):
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._state_path().write_text(json.dumps(state, indent=2))

    def _save_watermark(self, total_clips):
        """Advance the --last-run watermark, unless this run skipped workspaces.

        Time filters may advance it -- that is their purpose, and they still
        scan every workspace. A workspace-filtered run may not: the watermark
        is global, so moving it would make the next --last-run skip everything
        older in the workspaces this run never touched.
        """
        if self.only_workspaces:
            print("Workspace-filtered run — last-run state NOT updated "
                  "(it would skip older clips in the workspaces not selected).")
            return
        self.save_state({
            "last_successful_run": self.fetch_start_time,
            "total_clips": total_clips,
        })
        print("State saved for incremental runs (--last-run).")

    # ---- naming and downloads

    def _sanitize(self, name, max_length=50):
        s = re.sub(r"[^a-zA-Z0-9\- ]", "", str(name or ""))
        s = re.sub(r"\s+", "-", s.strip()).lower().strip("-")
        return s[:max_length] or "untitled"

    def filename_base(self, c):
        created = self._clip_created_at(c)
        date_str = created.strftime("%Y-%m-%d") if created else "unknown-date"
        clip_id = re.sub(r"[^a-zA-Z0-9]", "", str(c.get("id") or ""))[:8] or "noid"
        return f"{date_str}_{self._sanitize(c.get('title'))}_{clip_id}"

    def _has_file(self, month, base, exts):
        return any((month / f"{base}.{ext}").exists() for ext in exts)

    def _workspace_dirname(self, name, max_length=60):
        """Workspace name -> one safe path segment, readability preserved.

        Unlike _sanitize (filenames: lowercased and hyphenated) this keeps case
        and spaces, because these are top-level folders the user browses. Path
        separators and reserved characters become "_" so a name like
        "HOUSE/SYNTHPOP/RETRO" can't fan out into nested directories -- or, as
        ".." would, climb out of the archive entirely.
        """
        s = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "_", str(name or ""))
        s = re.sub(r"\s+", " ", s).strip(" .")  # trailing dots/spaces break Windows
        if not s or set(s) <= {".", "_", " "}:
            return "untitled-workspace"
        return s[:max_length].strip(" .") or "untitled-workspace"

    def _month_dir(self, c):
        created = self._clip_created_at(c)
        bucket = created.strftime("%Y-%m") if created else "unknown-date"
        workspace = self._workspace_dirname(c.get(WORKSPACE_KEY) or UNASSIGNED_DIRNAME)
        return self.archive_dir / workspace / bucket

    # Normalize common extension aliases so globs like *.jpg stay consistent.
    _EXT_ALIASES = {".jpeg": ".jpg", ".jpe": ".jpg", ".tiff": ".tif"}

    def _extension_for(self, url, content_type):
        path_ext = Path(urlparse(url).path).suffix.lower()
        if path_ext and re.fullmatch(r"\.[a-z0-9]{1,5}", path_ext) and re.search(r"[a-z]", path_ext):
            return self._EXT_ALIASES.get(path_ext, path_ext)
        if content_type:
            subtype = content_type.split(";")[0].strip().split("/")[-1].lower()
            special = {"mpeg": ".mp3", "jpeg": ".jpg", "plain": ".txt",
                       "svg+xml": ".svg", "octet-stream": None}
            if subtype in special:
                return special[subtype] or ".bin"
            if re.fullmatch(r"[a-z0-9]{1,5}", subtype):
                return f".{subtype}"
        return ".bin"

    def download_file(self, url, directory, base_name):
        """Raises on HTTP errors; deletes partial files; returns (path, bytes)."""
        # https-only in practice; http permitted solely to loopback (test servers).
        # This still refuses file://, ftp://, and http:// to internal/metadata hosts.
        parsed = urlparse(str(url))
        if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(f"refusing non-https URL: {url}")
        resp = requests.get(url, stream=True, timeout=600)
        resp.raise_for_status()
        ext = self._extension_for(url, resp.headers.get("Content-Type"))
        directory.mkdir(parents=True, exist_ok=True)
        filepath = directory / f"{base_name}{ext}"
        if not filepath.resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"refusing to write outside archive dir: {filepath}")
        size = 0
        try:
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=10*1024*1024):
                    f.write(chunk)
                    size += len(chunk)
        except Exception:
            filepath.unlink(missing_ok=True)
            raise
        return filepath, size

    # ---- Mango DRM Decryption Internals

    def _fetch_mango_license(self, clip_id):
        url = f"{M4A_API_BASE}/api/mango/rights"
        headers = {
            "Content-Type": "application/json",
            "Origin": "https://suno.com",
            "Referer": "https://suno.com",
        }
        payload = {
            "content_params": {"content_id": clip_id, "content_type": "clip"}
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _aes_gcm_decrypt(self, key, nonce, ciphertext_with_tag, aad):
        ciphertext = ciphertext_with_tag[:-16]
        tag = ciphertext_with_tag[-16:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        cipher.update(aad)
        return cipher.decrypt_and_verify(ciphertext, tag)

    def _unwrap_mango_keys(self, license_data, clip_id):
        glt = license_data.get("glt")
        if not glt:
            raise ValueError("Lizenz-Response enthält kein 'glt'")

        user_key = hashlib.sha256(glt.encode("utf-8")).digest()
        wrapped_key = base64.b64decode(license_data["key"])
        wrapped_iv = base64.b64decode(license_data["iv"])
        aad = clip_id.encode("utf-8")

        aes_key = self._aes_gcm_decrypt(user_key, wrapped_key[:12], wrapped_key[12:], aad)
        aes_iv = self._aes_gcm_decrypt(user_key, wrapped_iv[:12], wrapped_iv[12:], aad)
        return aes_key, aes_iv

    def _get_mango_file_size(self, url):
        headers = {"Range": "bytes=0-0"}
        resp = requests.get(url, headers=headers, timeout=30)
        if "Content-Range" in resp.headers:
            return int(resp.headers["Content-Range"].split("/")[-1])
        if "Content-Length" in resp.headers:
            return int(resp.headers["Content-Length"])
        raise ValueError("Dateigröße konnte nicht ermittelt werden.")

    def _decrypt_and_save_mango_m4a(self, clip_id, media_url, directory, base_name):
        license_data = self._fetch_mango_license(clip_id)
        aes_key, aes_iv = self._unwrap_mango_keys(license_data, clip_id)
        total_size = self._get_mango_file_size(media_url)

        directory.mkdir(parents=True, exist_ok=True)
        filepath = directory / f"{base_name}.m4a"

        offset = 0
        with open(filepath, "wb") as f_out:
            while offset < total_size:
                end = min(offset + MANGO_CHUNK_SIZE, total_size) - 1
                headers = {"Range": f"bytes={offset}-{end}"}

                resp = requests.get(media_url, headers=headers, timeout=30)
                encrypted_chunk = resp.content

                block_offset = offset // 16
                iv_int = int.from_bytes(aes_iv, byteorder="big")
                initial_value = iv_int + block_offset

                ctr_object = Counter.new(128, initial_value=initial_value)
                cipher = AES.new(aes_key, AES.MODE_CTR, counter=ctr_object)
                decrypted_chunk = cipher.decrypt(encrypted_chunk)

                f_out.write(decrypted_chunk)
                offset += MANGO_CHUNK_SIZE

        return filepath, filepath.stat().st_size

    # ---- orchestration

    def _wav_url_in_clip(self, c):
        for key in ("audio_url_wav", "wav_url", "wav_audio_url", "master_wav_url"):
            if c.get(key):
                return c[key]
        return None

    def _m4a_url_in_clip(self, c):
        media_urls = c.get("media_urls")
        if isinstance(media_urls, list):
            for entry in media_urls:
                if isinstance(entry, dict) and entry.get("url"):
                    u = entry["url"]
                    ct = entry.get("content_type", "").lower()
                    if u.lower().endswith(".m4a") or "m4a-opus" in ct:
                        return u
        return None

    def _build_jobs(self):
        """Returns (jobs, skipped). One job per file to fetch; writes per-clip JSON."""
        jobs, skipped = [], 0
        for c in self.clips:
            month = self._month_dir(c)
            base = self.filename_base(c)
            month.mkdir(parents=True, exist_ok=True)
            (month / f"{base}.json").write_text(json.dumps(c, indent=2, default=str))

            if self._has_file(month, base, AUDIO_EXTS):
                skipped += 1
            elif c.get("audio_url") and "forbidden" not in c["audio_url"].lower():
                jobs.append((c["audio_url"], month, base))

            if self.want_art:
                if self._has_file(month, base, IMAGE_EXTS):
                    skipped += 1
                elif c.get("image_url"):
                    jobs.append((c["image_url"], month, base))

            if self.want_wav:
                if list(month.glob(f"{base}.wav")):
                    skipped += 1
                else:
                    wav = self._wav_url_in_clip(c)
                    if wav:
                        jobs.append((wav, month, base))
                    elif c.get("id"):
                        jobs.append(("__convert__:" + c["id"], month, base))
                    else:
                        print("  WARNING: clip without id, skipping WAV conversion")
            if self.want_m4a:
                if list(month.glob(f"{base}.m4a")):
                    skipped += 1
                else:
                    clip_id = c.get("id")
                    m4a_url = self._m4a_url_in_clip(c)
                    if clip_id and m4a_url:
                        # Mango DRM Entschlüsselungsjob via custom internal Prefix einreihen
                        jobs.append((f"__mango__:{clip_id}|{m4a_url}", month, base))
                    else:
                        print("  WARNING: clip missing id or m4a media URL, skipping m4a archive")
        return jobs, skipped

    def _run_job(self, job):
        url, directory, base = job
        if url.startswith("__convert__:"):
            clip_id = url.split(":", 1)[1]
            self.api.request_wav(clip_id)
            url = self.api.get_wav_url(clip_id)
            return self.download_file(url, directory, base)

        if url.startswith("__mango__"):
            # Metadaten-Payload aus der Jobliste parsen
            payload = url.split(":", 1)[1]
            clip_id, media_url = payload.split("|", 1)
            return self._decrypt_and_save_mango_m4a(clip_id, media_url, directory, base)

        return self.download_file(url, directory, base)

    def _index_path(self):
        return self.archive_dir / "library_index.json"

    def is_partial_run(self):
        """True when this run deliberately covers only part of the library."""
        return bool(self.since or self.until or self.last_run or self.only_workspaces)

    def _load_index_clips(self):
        try:
            data = json.loads(self._index_path().read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        clips = data.get("clips") if isinstance(data, dict) else None
        return clips if isinstance(clips, list) else []

    def _merge_clips(self, existing, fresh):
        """Fresh clips win by id; entries the run never looked at are preserved."""
        by_id, loose = {}, []
        for c in list(existing) + list(fresh):
            cid = c.get("id")
            if cid:
                by_id[cid] = c  # later (fresh) overwrites earlier (existing)
            else:
                loose.append(c)  # no id to merge on; keep rather than drop
        merged = list(by_id.values()) + loose
        # Newest-first, matching how Suno returns the library.
        merged.sort(key=lambda c: (self._clip_created_at(c) or _EPOCH), reverse=True)
        return merged

    def _write_index(self):
        """Full runs replace the index; partial runs merge into it.

        A full run is authoritative -- clips deleted on Suno should disappear.
        A partial run is not: overwriting would shrink the index to just that
        run's slice, which is what a scheduled `--last-run` used to do to a
        complete archive on every single invocation.
        """
        clips = self.clips
        if self.is_partial_run():
            existing = self._load_index_clips()
            if existing:
                clips = self._merge_clips(existing, self.clips)
                print(f"Index: merged {len(self.clips)} fetched into "
                      f"{len(existing)} existing -> {len(clips)} clips.")
        counts = {}
        for c in clips:
            label = c.get(WORKSPACE_KEY) or UNASSIGNED_DIRNAME
            counts[label] = counts.get(label, 0) + 1
        index = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_clips": len(clips),
            "workspaces": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "clips": clips,
        }
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._index_path().write_text(json.dumps(index, indent=2, default=str))

    def run(self):
        self.stats = {"downloaded": 0, "skipped": 0, "errors": 0, "bytes": 0}
        self.fetch_all_clips()
        if not self.clips:
            if not self.fetch_complete:
                print("Could not fetch your library — see the error above.")
            else:
                print("No clips matched.")
                # Advance the watermark: a caught-up --last-run shouldn't re-scan
                # from the same point forever.
                self._save_watermark(0)
            return

        self._write_index()
        jobs, self.stats["skipped"] = self._build_jobs()
        print(f"Downloading {len(jobs)} files "
              f"({self.stats['skipped']} already archived) "
              f"with concurrency {DOWNLOAD_CONCURRENCY}...")

        lock = threading.Lock()
        done = [0]

        def work(job):
            try:
                filepath, size = self._run_job(job)
                with lock:
                    done[0] += 1
                    self.stats["downloaded"] += 1
                    self.stats["bytes"] += size
                    print(f"  [{done[0]}/{len(jobs)}] ok {filepath.name}")
            except Exception as e:
                with lock:
                    done[0] += 1
                    self.stats["errors"] += 1
                    print(f"  [{done[0]}/{len(jobs)}] FAILED {job[0][:80]}: {e}")

        if jobs:
            with ThreadPoolExecutor(max_workers=DOWNLOAD_CONCURRENCY) as pool:
                list(pool.map(work, jobs))

        print(f"\nDone. {self.stats['downloaded']} downloaded, "
              f"{self.stats['skipped']} skipped, {self.stats['errors']} errors, "
              f"{self.stats['bytes'] / 1e6:.1f} MB")

        if self.fetch_complete:
            self._save_watermark(len(self.clips))
        else:
            print("Fetch was incomplete — last-run state NOT updated. Re-run to retry.")
