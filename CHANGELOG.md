# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-11

Initial release.

### Added
- Archive your full Suno library: MP3 audio, cover art, and complete per-song metadata (prompt, tags, lyrics, duration, model, dates) as JSON, plus a master `library_index.json`
- Optional lossless WAV download via `--wav` (requests Suno's conversion and polls)
- Incremental sync with `--last-run`; date filtering with `--since`/`--until`
- Automatic browser-session auth (Chrome/Brave/Firefox/Safari/Arc/...) with `SUNO_COOKIE` manual fallback
- Concurrent downloads (4-worker pool); idempotent re-runs skip existing files
- `doctor` command to diagnose auth and API health
