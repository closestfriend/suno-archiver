# suno-archiver

Archive your entire Suno music library — MP3 audio, cover art, and full metadata — with one command.

## Why

Suno's web UI only lets you download tracks one at a time. If you've generated more than a handful, pulling them all by hand is tedious-to-impossible. This tool grabs your **entire** library in one command — audio, cover art, and full metadata as JSON — organized on your own disk.

Useful if you:

- have a large library (hundreds or thousands of generations) and want it all local — for a DAW, a dataset, offline access, or your own bookkeeping. A 1,600-track pull is one run, not 1,600 clicks.
- want your data in a structured, scriptable form — every track's prompt, tags, model, and timestamps in JSON, plus a single `library_index.json` you can grep or query.
- don't want to depend on the cloud staying put. Suno's Warner Music deal (early 2026) pulled free download access ahead of schedule; terms can change again. A local copy doesn't.

Run it on a schedule with `--last-run` and the archive stays current automatically.

> **Tested at scale.** A full **1,668-track library** spanning two years (2024–2026) archived in a single run — **5.7 GB**, 99.9% success rate, no rate-limiting or throttling. The handful of missing files were dead/transient links on Suno's CDN, not failures of the tool — and a re-run picks them up.

## What it grabs

| File | Details |
|---|---|
| `.mp3` | Audio (Suno's MP3 stream) |
| `.jpg` | Cover art |
| `.json` | Full metadata — prompt, tags, lyrics, duration, model version, created/updated dates |
| `library_index.json` | All songs in one file, grep/jq-friendly |
| `--wav` | Optional: triggers Suno's lossless conversion and downloads the WAV alongside the MP3 (slower — one conversion request per song) |

## Important

- **Personal backup of your own creations only.** Do not scrape other users' libraries.
- **Plan requirements (partly unverified):** confirmed working end-to-end on a **Pro** plan. Metadata and cover art don't depend on your plan. Free-tier **audio** is untested — Suno removed the web-UI *download button* for free accounts after the 2026 Warner deal, but this tool pulls audio straight from the library API's CDN URLs rather than using that button, so it may still work on free. If you try it on a free plan, a report (issue/PR) is welcome.
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
suno-archiver --no-art             # skip cover art (audio + metadata only)
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

## Resilient by design

Archiving thousands of files over an undocumented API means things will occasionally go wrong mid-run. The tool is built so that they don't cost you:

- **Per-file errors never abort the run.** A dead CDN link (403) or a transient hiccup (503) is counted and reported, then the run continues. You get a clear tally at the end: `3333 downloaded, 0 skipped, 3 errors`.
- **Expired sessions self-heal.** Suno's auth tokens are short-lived; the tool transparently re-mints them, and retries once on a 401 before giving up.
- **Interrupted runs are safe.** The `--last-run` watermark is only saved when a fetch completes cleanly — so a connection drop or a kill mid-run can never cause the *next* incremental sync to silently skip tracks. You just re-run.
- **Re-runs are free.** Idempotent skipping means re-running after a partial failure costs nothing for already-downloaded files; only the gaps are retried.

If the tool ever stops working entirely (Suno changed their API), `suno-archiver doctor` tells you *which* layer broke — your login, the auth exchange, or the library endpoint — so you know whether to re-log-in or wait for an update.

## Related

[replicate-predictions-downloader](https://github.com/closestfriend/replicate-predictions-downloader) — same idea for Replicate AI predictions: bulk-download all your generated outputs from Replicate's API.

## License

MIT — see [LICENSE](LICENSE).
