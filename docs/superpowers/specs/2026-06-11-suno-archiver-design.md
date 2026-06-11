# suno-archiver — Design

**Date:** 2026-06-11
**Status:** Approved by Hunter
**Package:** `suno-archiver` (PyPI name confirmed available)
**CLI:** `suno-archiver`

## Purpose

Archive a Suno user's own music library to local disk: MP3s, optional WAVs,
cover art, and complete metadata (prompt, style tags, lyrics, model, dates) —
with full-archive and incremental (`--last-run`) modes. Personal backup of the
user's own creations; a Pro/Premier plan is required for audio downloads.

Built on Suno's **undocumented** web API. The design treats that as a
first-class constraint: all endpoint knowledge is isolated in one adapter
module, failures are loud and diagnostic, and a `doctor` command exists to
distinguish "your auth broke" from "Suno changed their API."

## Non-goals (v1)

- Music generation (this is an archiver, not an API client)
- Videos, stems, playlists/workspaces, liked-only filtering (v1.x candidates)
- ID3/metadata embedding into audio files (v1.1, via mutagen)
- Free-tier audio downloads (not entitled post-Warner; tool fails politely)
- Node port (Python only; same playbook available later if wanted)

## Architecture

```
suno_archiver/
├── __init__.py   # __version__, public exports
├── auth.py       # cookie acquisition + Clerk JWT lifecycle
├── suno_api.py   # THE adapter: every endpoint, header, pinned version
├── core.py       # orchestration: fetch → filter → download pool → state
└── cli.py        # Click interface
```

### auth.py

Cookie acquisition, in order:
1. `SUNO_COOKIE` env var / `.env` (explicit override wins; also the headless path)
2. `rookiepy` browser extraction: scan Chrome/Firefox/Safari/Arc/etc. for the
   suno.com `__client` cookie

Clerk JWT lifecycle (mechanics confirmed from gcui-art/suno-api, June 2026):
- `GET https://auth.suno.com/v1/client?__clerk_api_version=2025-11-10&_clerk_js_version=5.117.0`
  (both version params pinned as constants in auth.py)
  with `Authorization: <__client cookie value>` → session id
- `POST https://auth.suno.com/v1/client/sessions/{sid}/tokens?...` → short-lived JWT
- JWTs live minutes: re-mint proactively when older than ~30s at request time,
  plus one automatic re-mint-and-retry on any 401 before failing loud.

### suno_api.py — the isolation boundary

Owns base URL `https://studio-api.prod.suno.com`, all paths, headers, and the
pinned Clerk version params. Nothing outside this module knows a Suno URL.

- `list_library(page)` → `GET /api/feed/v2?page=N&hide_disliked=true&hide_gen_stems=true&hide_studio_clips=true`
  (returns list of clip dicts; newest-first; empty list = end of pagination)
  - **Open question to resolve in implementation, first task:** recon found two
    candidates — `/api/feed/v2` (Suno_DownloadEverything, private library) and
    `/api/feed/` (SunoSync's "My Library"). Verify against Hunter's real
    account on day one; the adapter makes switching a one-line change.
- `request_wav(clip_id)` → `POST /api/gen/{clip_id}/convert_wav/`
- `get_wav_url(clip_id)` → poll `GET /api/gen/{clip_id}/wav_file/` every 2s,
  timeout 120s, return URL or raise
- All failures raise `SunoApiError(status, detail)`.

Known clip fields (recon from SunoSync + Suno_DownloadEverything, June 2026):
`id`, `title`, `audio_url`, `image_url`, `display_name`, `created_at`,
`is_public`, `is_trashed`, and `metadata{prompt, tags, lyrics, text, duration, type}`.
The archiver stores the **entire raw clip dict** in the per-song JSON so field
drift never loses data.

### core.py — orchestration (ports the proven replicate-downloader-py shape)

Hard-won invariants carried over from this week's work, all present from day one:
- All datetimes timezone-aware UTC (naive local time corrupted watermarks before)
- `--last-run` watermark = **fetch start time**, saved **only when
  `fetch_complete` is True** (interrupted runs must not cause silent skips)
- Client-side `--since`/`--until` filtering with newest-first early-stop pagination
- Unparseable dates raise `ValueError` (never silently disable a filter)
- Download pool: `ThreadPoolExecutor(max_workers=4)`, flat job list
- Downloads `raise_for_status()`, stream to disk, delete partial file on error
- File extension from URL when sane, else from response `Content-Type`, else `.bin`

WAV flow: jobs that need WAV first check the clip dict for an existing WAV URL
(keys seen in the wild: `audio_url_wav`, `wav_url`, `wav_audio_url`,
`master_wav_url`), then request conversion + poll. WAV jobs run in the same
pool; polling sleeps inside the worker.

### On-disk layout

```
suno_archive/
├── 2026-06/
│   ├── 2026-06-10_<sanitized-title>_<id8>.mp3
│   ├── 2026-06-10_<sanitized-title>_<id8>.wav    (--wav only)
│   ├── 2026-06-10_<sanitized-title>_<id8>.jpg    (cover art)
│   └── 2026-06-10_<sanitized-title>_<id8>.json   (full raw clip metadata)
├── library_index.json          (master index: all clips' metadata, one file)
└── .suno-archiver-state.json   (last-run watermark; lives with the archive)
```

Month buckets (`YYYY-MM/`) because Suno libraries are date-shaped. Filenames
follow the established `date_title_id8` pattern; title sanitized to
`[a-z0-9-]`, max 50 chars, `untitled` fallback. Re-runs into the same archive
dir are expected: existing files with the same name are skipped (idempotent),
`library_index.json` is rewritten whole each run.

## CLI surface

```
suno-archiver                    # full archive: MP3 + covers + metadata
suno-archiver --wav              # also fetch WAVs (slow: convert+poll; opt-in)
suno-archiver --last-run         # incremental since last successful run
suno-archiver --since "2 weeks ago" [--until DATE]
suno-archiver --dir PATH         # archive root (default ./suno_archive)
suno-archiver doctor             # auth probe + 1-page feed probe + diagnosis
```

Mutual exclusion: `--last-run` with `--since`/`--until` is an error (matches
the sibling tools). `--wav` is opt-in per run; docs recommend
`--wav --last-run` as the steady-state habit. Exit code 1 when nothing could
be fetched due to an error.

## Error handling

- 401 anywhere → one silent JWT re-mint + retry → then fail loud:
  "Suno session expired or invalid. Log into suno.com in your browser and
  re-run (or update SUNO_COOKIE)."
- Other `SunoApiError` during fetch → `fetch_complete = False`, continue with
  partial results, state not saved, summary names the failure.
- Per-file download errors → counted, reported, never abort the run.
- `doctor` checks in order: cookie found → Clerk exchange works → feed page 1
  fetches → prints versions and a one-line verdict per step. Its job is making
  "Suno changed something" diagnosable by users, not just the maintainer.

## Testing

`unittest` + local `ThreadingHTTPServer` fakes (pattern proven in
replicate-predictions-downloader-py):
- Fake Clerk: token minting, expiry, 401-then-refresh-then-success sequence
- Fake feed: multi-page pagination, newest-first ordering, early-stop
- Fake WAV: conversion request + poll that resolves on the Nth attempt + timeout case
- Fixtures: sanitized real response shapes from the June 2026 recon
- State safety: complete vs interrupted fetch (watermark semantics)
- Filename/sanitization/extension unit tests
- Zero live API calls in tests

## Dependencies

`requests`, `click`, `python-dotenv`, `rookiepy`. Build: hatchling.
`requires-python >= 3.9`. Dev: stdlib unittest only.

## Posture / README requirements

- Lead with why: your library is yours; platforms change terms (Warner deal
  removed free downloads overnight) — keep local copies.
- Explicit: personal backup of your own creations only; audio requires a paid
  plan; the tool never bypasses entitlements.
- Explicit: built on an undocumented API, can break any day; `doctor` first,
  then check for updates / file an issue.

## Risks

| Risk | Mitigation |
|---|---|
| Suno changes endpoints/auth | Adapter isolation; pinned versions in one place; `doctor`; loud errors |
| Clerk JWT mechanics drift | Reference impl (gcui-art) actively maintained; auth.py is small |
| rookiepy breaks on an OS/browser | `SUNO_COOKIE` env fallback always works |
| WAV conversion rate limits | Opt-in flag; polling backoff; per-file failure tolerance |
| ToS enforcement post-Warner | Personal-backup posture; entitlement-respecting; honest README |
