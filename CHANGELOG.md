# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
