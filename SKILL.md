---
name: gemini-web
description: Generate images (Nano Banana) and videos (Veo) with the user's Gemini subscription through the logged-in gemini.google.com web app, never the API. Use for Gemini image generation or editing, Veo text-to-video or image-to-video, and every video-generation request (it replaced Grok video on 2026-10-24).
---

# gemini-web — subscription image + video from the console (no API)

Two CLIs on PATH drive the logged-in Gemini web app in an automation Chrome profile and bill the Gemini subscription: `gemini-img` (images) and `gemini-vid` (videos). Each run opens a fresh tab with `bh-open`, works there in the background, and closes it. No step needs the window in the foreground.

## Settings

`~/gemini-web/config.env` (local, not in the repo; environment variables override it):

```
GEMINI_PROFILE=<profile>          # automation Chrome profile for bh-open
GEMINI_ACCOUNT=<email>            # must be the signed-in account, or the run stops (exit 4)
GEMINI_AUTHUSER=<n>               # /u/<n>/ index of that account in Gemini
```

Read that file for the profile and account in use; do not switch accounts on your own. A project may pin its own values by setting these variables when it calls the CLIs.

## Usage

```bash
# image -> video (Veo). With -o the job is resumable; prints one JSON line.
gemini-vid -i still.png -o /abs/out/clip.mp4 "Photorealistic, keep the scene. Clouds drift. Locked-off static tripod camera."

# text -> video
gemini-vid "a paper boat sailing down a rain puddle, cinematic" /abs/outdir

# text -> image, image -> image (Nano Banana)
gemini-img "a serene mountain lake at sunrise, photorealistic" /abs/outdir
gemini-img -i lake.png "make it deep winter, frozen lake, snow" /abs/outdir
```

- `gemini-vid` output: `{"videos": [path], "bytes": n, "chat": url}`. Clips are 720p H.264, 24 fps, 10 s, with an AAC track; a vertical still gives 720×1280. Usually ready in 1–3 min.
- `gemini-img` output: `{"images": [paths], "limit": false, "count": n}`. Usually about 1 min.
- Flags: `-i` input image, `-p` filename prefix, `-o` exact output file (`gemini-vid` only). Optional last positional argument = output directory (default `~/gemini-web/out`).
- `GEMINI_TIMEOUT` (s): `gemini-vid` waits 1800 by default, checking every `GEMINI_POLL` (60) s; `gemini-img` 420.
- Run calls one after another, not in parallel: each step drives the tab bh-open just opened in the same browser session.
- With `-o`, `gemini-vid` keeps the chat url in `<out>.chat` until the download succeeds. Running the same command again continues that job instead of paying for a new one.
- Veo moves the camera unless told not to. For a still shot write "Locked-off static tripod camera: the framing does not move, zoom or pan at all" and name what must stay in frame.

Exit codes: 2 timeout (or output exists), 3 limit or refusal, 4 logged out or wrong account, 5 extraction failed, 6 image upload failed. On 3 or 4 stop, notify the user with the exact reply, and check `https://gemini.google.com/usage`. A login wall is human-only: never type credentials.

## When NOT to use

- The cookie API (`gemini_webapi`) is walled for media (bot-session wall #344): text works, images and video come back as "limit resets". Use these browser CLIs for media.
- The Gemini API (Veo API) bills per second outside the subscription. Use it only on the user's explicit OK.
- Another provider was requested → use that provider's skill.

## How it works (for debugging)

- **Fresh tab per step.** An open Gemini tab never shows a finished video until it is reloaded, so `gemini-vid` sends the job in one tab, then opens the chat url in a new tab once a minute to check. Never `goto_url()`/reload and then `js()` in the same tab: a freshly navigated target's `Runtime.evaluate` can hang. bh-open's tab is already loaded.
- **Upload = synthetic paste.** The image bytes go over CDP in 24K chunks (larger messages are refused: "chunk is longer than limit"), become a `File` in a `DataTransfer`, and are dispatched as a `paste` event on `rich-textarea [contenteditable]`. This replaced the "Upload & tools" menu, whose items live in shadow DOM and only render while the tab is visible. `gemini-vid` converts the still to JPEG first (about 5× smaller, faster paste).
- **Send.** Insert the prompt with `execCommand('insertText')`, wait until `button[aria-label*="Send"]` is enabled (it stays disabled while the image uploads), click it, and wait for the url to become `/app/<chat id>`.
- **Video done-signal.** `model-response video` with an https `currentSrc`. Do not gate on `duration`/`readyState`: Gemini mounts the finished video with `preload="metadata"` and never loads it until played. Download host-side with `curl -L` and a cookie jar written from CDP `Storage.getCookies` (deleted right after).
- **Image done-signal.** A new blob `<img>` (naturalWidth > 256) plus a Download button, extracted with `canvas.toDataURL`. Pre-existing blobs (the input thumbnail) are skipped.
- **Background mode.** browser-harness refuses `Target.activateTarget` in background mode; neither CLI calls it. Tabs are closed with `Target.closeTarget` on the tab bh-open returned, so other Gemini tabs (a running job) are left alone.
- **Tier.** The account badge in the sidebar is authoritative (shows "Pro"), not `list_models()`.

## Files

- CLIs: `scripts/gemini-vid` (Python), `scripts/gemini-img` (bash). Symlink them onto PATH: `ln -sf "$PWD/scripts/gemini-"{img,vid} ~/bin/`.
- Drivers (run inside `browser-harness -c`): `scripts/driver_tab.py` (video send/check), `scripts/driver_img.py` (images).
- Cookie-API diagnostics, not used by the CLIs: `scripts/pull_cookies.py`, `scripts/diagnose_cookie_api.py`, `scripts/cookie_bridge_*.py`.
