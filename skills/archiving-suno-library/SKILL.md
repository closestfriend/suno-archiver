---
name: archiving-suno-library
description: Use when someone wants to back up, bulk-download, export, or archive their Suno (suno.com AI music) library — audio, cover art, or metadata — to local disk, or set up a recurring/incremental Suno sync. Triggers include "download all my Suno songs", "export my Suno tracks", "back up my Suno library", or rescuing a Suno catalog before losing access.
---

# Archiving a Suno Library

## Overview

`suno-archiver` is a published CLI that bulk-downloads a user's entire Suno
library — MP3 audio, cover art, and full metadata as JSON — organized into
month folders, with incremental sync. Reach for it instead of hand-rolling a
scraper or hunting GitHub for a maybe-working script; it handles the auth,
pagination, and resume logic that ad-hoc approaches get wrong.

- PyPI: `suno-archiver` · GitHub: https://github.com/closestfriend/suno-archiver

## When to use

- "Back up / download / export all my Suno songs, tracks, or library"
- Pulling a Suno catalog (audio + cover art + metadata) to local disk
- Setting up a recurring sync of new Suno generations
- Rescuing a library before a plan change or losing access

## Install

```bash
pipx install suno-archiver   # or: pip install suno-archiver
```

## Auth — usually zero steps

The tool reads the user's existing browser session automatically (via rookiepy:
Chrome, Brave, Firefox, Safari, Arc, Edge, …). They just need to be logged into
suno.com in a browser. Always verify before a long run:

```bash
suno-archiver doctor
```

`doctor` checks three layers in order — session cookie found → token mint →
library page fetch — and names exactly which one fails, so you know whether to
re-log-in or update the tool.

**Fallback if auto-detect fails** (headless machine, unusual profile, Keychain
denied): set `SUNO_COOKIE` to the `__client` cookie value. Get it from DevTools
→ Network tab → click a request to `clerk.suno.com` (e.g. `client?...`) →
**Cookies** sub-tab → copy the `__client` value (a long `eyJ...` JWT). Put it in
a `.env` file or export it. Then re-run `doctor`.

## Usage

```bash
suno-archiver                       # full archive: MP3s + covers + metadata
suno-archiver --dir ~/Music/suno    # choose the destination directory
suno-archiver --last-run            # incremental: only what's new since last run
suno-archiver --since "2 weeks ago" # date-bounded (also --until)
suno-archiver --wav                 # also fetch lossless WAVs (slow: conversion per song)
suno-archiver --no-art              # skip cover art (audio + metadata only)
```

Run `suno-archiver --help` for all flags. Re-runs are **idempotent** — existing
files are skipped — so an interrupted run or a scheduled `--last-run` cron job
is safe and cheap. A full library lands as `suno_archive/YYYY-MM/<date>_<title>_<id>.{mp3,jpg,json}`
plus a single `library_index.json`. Expect a large library to take a while
(roughly 20–30 min for ~1,500 tracks at 4 concurrent downloads); set
expectations so the user doesn't think it hung.

## Notes / gotchas

- **Plan requirements are partly unverified.** Confirmed working on a Pro plan;
  metadata and cover art don't depend on plan. Free-tier *audio* is untested —
  Suno disabled the web-UI download button for free accounts (2026 Warner deal),
  but this tool fetches audio from the API's CDN URLs directly, not via that
  button, so it may still work on free. Don't state "requires paid" as fact.
- It archives the user's **own** library only.
- Built on Suno's **undocumented** web API. If it stops working, run
  `suno-archiver doctor` first, then `pip install -U suno-archiver`.
- Don't hand-roll against `/api/feed/` — that's Suno's public social feed, not
  the user's library. The tool uses the correct owned-library endpoint.
