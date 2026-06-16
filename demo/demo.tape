# suno-archiver promo demo — render with:  vhs demo/demo.tape
# Produces demo.gif, usable as the README hero AND a social clip.
#
# SAFETY (read before recording):
#   - `suno-archiver doctor` NEVER prints your cookie/token (audited) — safe to show.
#   - Do NOT `cat .env`, run `env`, or `export SUNO_COOKIE=...` on camera.
#   - Run from a dir whose .env holds a SUNO_COOKIE you're willing to rotate after,
#     or just be logged into suno.com so rookiepy handles auth invisibly.
#   - The slice below is small + `--no-art`, so the clip stays short and tidy.

Output demo.gif
Require suno-archiver

Set Shell "bash"
Set FontSize 22
Set Width 1280
Set Height 720
Set Padding 32
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set PlaybackSpeed 1.0

# --- Beat 1 · the hook (typed as a shell comment = on-screen text, harmless) ---
Type "# 1,600 songs trapped in Suno — downloadable one... at... a... time."
Sleep 800ms
Enter
Sleep 1200ms
Type "# not anymore."
Sleep 600ms
Enter
Sleep 1200ms

# --- Beat 2 · auth just works (doctor reveals no secrets) ---
Type "suno-archiver doctor"
Enter
Sleep 4s

# --- Beat 3 · the magic — a real slice, audio + metadata only ---
Type "suno-archiver --since '1 week ago' --no-art --dir demo_archive"
Enter
Sleep 7s

# --- Beat 4 · the reveal — tidy, date-bucketed, on your own disk ---
Type "ls demo_archive/2026-06/ | head"
Enter
Sleep 3s

# --- CTA ---
Type "# pip install suno-archiver   ·   github.com/closestfriend/suno-archiver"
Sleep 700ms
Enter
Sleep 2800ms
