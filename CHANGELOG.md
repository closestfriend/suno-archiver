# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-08-09

**If you archived with 1.x, your archive is incomplete — please re-run.**

### Fixed
- **Multi-workspace support — the archiver was only ever fetching part of your library.** Every version through 1.0.1 hard-coded `/api/project/default`, which Suno labels *"Workspace for unassigned clips"*. Any song filed into a named workspace was invisible to the tool, and the run still reported `0 errors`, so there was no way to notice. The tool now enumerates all workspaces via `/api/project/me` and archives every one. Measured on a real 4,257-clip library: 1.0.1 retrieved 1,768 clips and silently missed **2,489 — 58% of the library**.
- Workspaces are de-duplicated by clip id: Suno lists the unassigned bucket a second time under its display name ("My Workspace"), and the first workspace to yield a clip owns it.
- Failure to enumerate workspaces degrades to the unassigned bucket, prints a loud warning, and marks the run incomplete so `--last-run` state is not saved.
- **`library_index.json` was destroyed by every partial run.** The index was overwritten with only the clips that run fetched, so the scheduled `--last-run` workflow the README recommends shrank a complete index to the newest handful on each invocation — verified against a real archive: 4,257 clips → 40. Audio and per-clip JSON were never affected (idempotent skipping), only the index. Full runs still replace the index (they are authoritative, so clips deleted on Suno drop out); partial runs now merge by clip id, newest-first.
- A workspace-filtered run no longer advances the `--last-run` watermark. The watermark is global, so moving it after archiving a subset would make the next incremental sync skip everything older in the workspaces that run never touched.

### Changed
- **BREAKING — archive layout.** Clips now land in `<workspace>/YYYY-MM/` instead of `YYYY-MM/`; the unassigned bucket is `_unassigned/`. Existing 1.x archives are not migrated: re-running builds the new tree alongside the old one, and the old `YYYY-MM/` folders can be deleted once you've confirmed the new archive. Workspace names are sanitized to a single path segment, so `HOUSE/SYNTHPOP/RETRO` becomes `HOUSE_SYNTHPOP_RETRO` rather than nesting.
- Each clip's JSON now carries a `workspace` field, and `library_index.json` gains a `workspaces` summary of per-workspace counts.

### Added
- `--workspace NAME` (repeatable, `-w`) to archive only selected workspaces. Matching is case-insensitive and accepts either the Suno name or the on-disk folder name. An unrecognized name is an error listing the available workspaces — never a silent empty archive.
- `suno-archiver workspaces` lists your workspaces and clip counts, so `--workspace` has something to name.
- `doctor` gained a fourth step covering workspace enumeration, since that failure mode is otherwise silent.
- `SunoApi.list_projects()`; `list_library()` takes a `project` argument.
- Declared dev dependencies — `pip install -e ".[dev]"` then `pytest`.

### Internal
- Test suite expanded to 90, covering workspace enumeration, cross-workspace de-duplication, layout, workspace-name sanitization (including path-traversal containment), graceful degradation when workspace listing fails, index merge-vs-replace semantics, and watermark behaviour under filtering.

## [1.0.1] - 2026-06-13

Hardening release following a multi-angle code audit.

### Fixed
- **Idempotency**: cover art served as PNG/WebP (not JPEG) was re-downloaded on every run because the skip check hard-coded `.jpg`. Skip now matches the actual written extension for both audio and images.
- **Loud failure on API drift**: if Suno changes their library response shape, the tool now raises a clear error (and `doctor` reports it) instead of silently producing an empty archive.
- **Incremental watermark**: a caught-up `--last-run` (zero new clips) now advances its watermark instead of re-scanning from the same point every time.

### Security
- Clip `id` (server-supplied) is now sanitized before use in filenames, and downloads are asserted to stay within the archive directory (path-traversal hardening).
- Download URLs must be `https` (http permitted only to loopback for tests) — blocks `file://`, `ftp://`, and http-to-internal-host fetches.

### Added
- `--no-art` flag to skip cover art and archive audio + metadata only.

### Internal
- Test suite expanded to 60 (added `doctor` coverage, the new fixes, and edge cases). Packaging: classifier set to Production/Stable; `rookiepy` capped below 1.0.

## [1.0.0] - 2026-06-11

Initial release.

### Added
- Archive your full Suno library: MP3 audio, cover art, and complete per-song metadata (prompt, tags, lyrics, duration, model, dates) as JSON, plus a master `library_index.json`
- Optional lossless WAV download via `--wav` (requests Suno's conversion and polls)
- Incremental sync with `--last-run`; date filtering with `--since`/`--until`
- Automatic browser-session auth (Chrome/Brave/Firefox/Safari/Arc/...) with `SUNO_COOKIE` manual fallback
- Concurrent downloads (4-worker pool); idempotent re-runs skip existing files
- `doctor` command to diagnose auth and API health
