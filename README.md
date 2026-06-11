# suno-archiver

Archive your entire Suno music library — MP3 audio, cover art, and full metadata — with one command.

## Why

Suno's Warner Music deal (early 2026) removed free download access ahead of schedule for many accounts. Your creations live in Suno's cloud; this tool gives you a local copy under your own control. Run it on a schedule and you'll never lose a track.

## What it grabs

| File | Details |
|---|---|
| `.mp3` | Audio (128 kbps Suno stream) |
| `.jpg` | Cover art |
| `.json` | Full metadata — prompt, tags, lyrics, duration, model version, created/updated dates |
| `library_index.json` | All songs in one file, grep/jq-friendly |
| `--wav` | Optional: triggers Suno's lossless conversion and downloads the WAV alongside the MP3 (slower — one conversion request per song) |

## Important

- **Personal backup of your own creations only.** Do not scrape other users' libraries.
- **Audio downloads require a paid Suno plan** (Pro or Premier). Metadata-only runs work on free plans.
- **Undocumented API** — Suno can change or break this at any time. Run `suno-archiver doctor` if something stops working, and check for updates with `pip install -U suno-archiver`.

## Install

```bash
pipx install suno-archiver   # recommended: isolated environment
# or
pip install suno-archiver
```

Requires Python 3.9+.

## Auth

### Primary: just be logged in to suno.com in your browser

That's it. `suno-archiver` uses [rookiepy](https://github.com/thewh1teagle/rookiepy) to read your existing browser session cookie automatically. Works with Chrome, Brave, Firefox, Safari, Arc, Edge, and more — no manual steps needed.

```bash
suno-archiver        # rookiepy finds your session automatically
```

### Fallback: set SUNO_COOKIE manually

Use this if browser auto-detection fails (headless servers, CI, multiple profiles, or just for troubleshooting):

1. Open [suno.com](https://suno.com) in Chrome and make sure you're logged in.
2. Open DevTools → Network tab → reload the page.
3. Click any request to `clerk.suno.com` (look for `client?__clerk_api_version=...`).
4. Select the **Cookies** tab in the request detail panel.
5. Find the `__client` cookie — it's a long three-segment JWT (looks like `eyJ...`).
6. Copy its value.

```bash
# .env file or shell environment
SUNO_COOKIE=eyJhbGci...   # paste the full __client value here
```

Then run `suno-archiver doctor` to confirm it's working.

## Usage

```bash
suno-archiver                      # full archive: MP3s + covers + metadata
suno-archiver --wav                # also WAVs (slower: conversion per song)
suno-archiver --last-run           # only what's new since the last run
suno-archiver --since "2 weeks ago"
suno-archiver --dir ~/Music/suno_archive
suno-archiver doctor               # diagnose auth/API issues
```

Re-runs are **idempotent** — existing files are skipped, so `--last-run` on a cron job keeps your archive current without re-downloading anything.

## What lands on disk

```
suno_archive/
├── 2026-06/
│   ├── 2026-06-02_concrete-syncope_49291ca0.mp3
│   ├── 2026-06-02_concrete-syncope_49291ca0.jpg     (cover art)
│   └── 2026-06-02_concrete-syncope_49291ca0.json    (full metadata)
├── library_index.json    (everything, searchable with jq/grep)
└── .suno-archiver-state.json
```

Songs are organized into `YYYY-MM/` month folders. The state file records the last run timestamp for `--last-run` incremental syncs.

## Related

[replicate-predictions-downloader](https://github.com/closestfriend/replicate-predictions-downloader) — same idea for Replicate AI predictions: bulk-download all your generated outputs from Replicate's API.

## License

MIT — see [LICENSE](LICENSE).
