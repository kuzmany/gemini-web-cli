# gemini-web

Generate and edit **images and video from the command line using your Google Gemini
subscription** — not the paid API. It drives your real, already-logged-in
`gemini.google.com` tab over the Chrome DevTools Protocol, so images come from Nano Banana
and video from Veo, billed to the subscription you already pay for. No API key exists
anywhere in this repo.

Two CLIs, four modes:

```bash
# text -> image  (Nano Banana)
gemini-img "a serene mountain lake at sunrise, photorealistic"

# image -> image  (edit; preserves composition)
gemini-img -i lake.png "make it deep winter, frozen lake, snow"

# text -> video  (Veo, 720p 10s + audio)
gemini-vid "a paper boat sailing down a rain puddle, cinematic"

# image -> video  (animate a still); -o gives an exact, resumable output file
gemini-vid -i lake.png -o ~/clips/lake.mp4 "mist drifts, water ripples, locked-off static camera"
```

Each command prints one bare JSON line with the saved path — easy to pipe or hand to an
agent:

```json
{"videos": ["/home/you/clips/lake.mp4"], "bytes": 6507368, "chat": "https://gemini.google.com/u/0/app/..."}
```

## Requirements

- [browser-harness](https://github.com/browser-use/browser-harness) on your PATH, plus a
  `bh-open [profile] <url>` command that opens a tab in the harness Chrome and prints
  `{"target_id": ...}`.
- A Chrome profile driven by that harness that is **logged in** to `gemini.google.com`. If a
  run hits a login wall, log in yourself.
- A Gemini subscription tier that includes image/video (Veo access varies by plan).
- `curl` and `python3` on PATH.

## Install

```bash
git clone <this-repo> gemini-web
cd gemini-web
ln -sf "$PWD/scripts/gemini-"{img,vid} ~/bin/     # or anywhere on PATH
```

Outputs default to `~/gemini-web/out/`; override with `GEMINI_OUT` or a second positional
argument.

## Flags and environment

| | |
|---|---|
| `-p <prefix>` | output filename prefix |
| `-i <path>` | input image (enables image→image / image→video) |
| 2nd positional arg | output directory |
| `GEMINI_OUT`, `GEMINI_PREFIX` | defaults for the above |
| `GEMINI_TIMEOUT` | seconds to wait; default 420 (image) / 1800 (video) |
| `-o <path>` | `gemini-vid` only: exact output file; the job is resumable (`<path>.chat`) |
| `GEMINI_PROFILE` | harness Chrome profile passed to `bh-open` |
| `GEMINI_ACCOUNT` | email that must be signed in; the run stops with exit 4 otherwise |
| `GEMINI_AUTHUSER` | the `/u/<n>/` index of that account in Gemini (default `0`) |
| `GEMINI_POLL` | `gemini-vid`: seconds between checks (default 60) |

Settings can also live in `~/gemini-web/config.env` as `KEY=value` lines; the environment
wins. Run one generation at a time: each step drives the tab `bh-open` just opened.

Exit codes: `2` timeout, `3` limit or refusal served by Gemini, `4` no composer / login
wall, `5` video extraction failed, `6` image upload failed.

## How it works

Everything crosses the CDP/HTTPS channel, so it behaves identically whether Chrome runs on
the same machine or a remote one over a tunnel — there is no shared-filesystem step.

- **A fresh tab per step.** Each run (and each video check) opens a new tab with `bh-open`,
  works in it in the background, and closes it. A fresh tab is already a new chat, and it is
  the only reliable way to see a finished video: an open Gemini tab does not show it until
  reloaded.
- **Upload = synthetic paste** (image→image, image→video). The file's base64 is pushed into
  the page in 24K chunks, rebuilt as a `File` in a `DataTransfer`, and dispatched as a
  `paste` event on the composer. No upload menu, no file chooser, no foreground window.
- **Send** — insert the prompt, wait until the Send button is enabled (it stays disabled
  while an image uploads), click it. `gemini-vid` then records the chat url.
- **Images out** — a rendered blob `<img>` plus a Download button is the done-signal; the
  bytes come back through `canvas.toDataURL` (the blob is same-origin, so the canvas is not
  tainted).
- **Video out** — the finished `<video>`'s `currentSrc` is a normal https mp4 URL. Cookies
  are read via CDP `Storage.getCookies` into a temporary Netscape jar, and `curl` fetches the
  URL from the host running the CLI.

## Gotchas worth knowing

These are load-bearing; each one cost a debugging session.

- **An open tab never sees the finished video.** It keeps showing "I'm generating your
  video" long after the video is ready. Check from a freshly opened tab.
- **The upload menu only works in a visible tab.** Its items live in shadow DOM inside a CDK
  overlay that only paints while `document.visibilityState === 'visible'`. The paste upload
  avoids the menu entirely.
- **CDP messages have a size limit.** Push base64 in ~24K chunks; a 200K chunk fails with
  "chunk is longer than limit".
- **Never gate video readiness on `duration` or `readyState`.** Gemini mounts the finished
  `<video>` with `preload="metadata"` and never loads it until played, so `readyState` stays
  `0` and `duration` stays `NaN`. Gate on an https `currentSrc`.
- **Never navigate, then evaluate.** A freshly navigated target can hang
  `Runtime.evaluate`. Open a new tab instead.
- **Background mode refuses `Target.activateTarget`.** Nothing here calls it.
- **Veo moves the camera unless told not to.** For a still shot say "locked-off static
  tripod camera: the framing does not move, zoom or pan at all".

## Scripts

- `scripts/gemini-img`, `scripts/gemini-vid` — the CLIs (symlink onto PATH).
- `scripts/driver_tab.py` (video send/check), `scripts/driver_img.py` (images) — drivers, run inside `browser-harness -c`.
- `scripts/pull_cookies.py`, `scripts/diagnose_cookie_api.py` — diagnostics for the
  cookie-API path (`gemini_webapi`). Not used by the CLIs, and note that the cookie API is
  bot-walled for media: text works, image/video return "limit resets". That wall is the
  reason this project drives a real browser instead.

## Notes

This automates *your own* logged-in session against your own subscription, the same actions
you could perform by hand. Google may change the Gemini DOM at any time and break the
selectors — the gotchas above are the usual suspects when it does. Respect Gemini's terms
and rate limits.
