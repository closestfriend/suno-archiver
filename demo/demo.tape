# suno-archiver promo demo — render with:  vhs demo/demo.tape
# (launch with the binary on PATH, e.g.  PATH="$PWD/.venv/bin:$PATH" vhs demo/demo.tape,
#  or after `pipx install suno-archiver`). Produces demo.gif — README hero + social clip.
#
# SAFETY: be logged into suno.com so rookiepy auths invisibly (no secret on disk).
#   Do NOT `cat .env`, run `env`, or `export SUNO_COOKIE=...` on camera.
#   The hidden setup uses a fresh temp dir so the counter shows a clean download.
#
# Note: this clip shows a recent slice for a tight runtime. The scale story
# (full 1,600+ track library) lives in the README + caption, not the clip.

Output demo.gif
Require suno-archiver

Set Shell "bash"
Set FontSize 22
Set Width 1280
Set Height 720
Set Padding 32
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

# --- Hidden setup: clean working dir (auth via your logged-in browser) ---
Hide
Type "cd /tmp && rm -rf suno-demo && mkdir suno-demo && cd suno-demo && clear"
Enter
Sleep 800ms
Show

# --- Beat 1 · the hook ---
Type "# suno only lets you download one song at a time"
Sleep 500ms
Enter
Sleep 1000ms

# --- Beat 2 · the hero: one command, the counter floods, zero errors ---
Type "suno-archiver --since '2 weeks ago' --no-art --dir suno_backup"
Enter
Sleep 9s

# --- Beat 3 · the reveal: tidy, date-bucketed, on your own disk ---
Type "ls suno_backup/2026-06/ | head"
Enter
Sleep 3s

# --- Beat 4 · CTA ---
Type "# pip install suno-archiver   ·   github.com/closestfriend/suno-archiver"
Sleep 700ms
Enter
Sleep 2500ms
