---
name: gemini-web
description: >-
  Generate or edit images and videos from the command line using the user's Google
  Gemini SUBSCRIPTION (Ultra) — never the paid API / API credits. Drives the real
  logged-in gemini.google.com tab in the browser-harness Chrome (browser-piggyback),
  so it uses Nano Banana (images) and Veo (video) billed to the subscription. Four
  modes: text→image, text→video, image→image (edit), image→video (animate a still).
  This skill should be used when the user asks to "generate image/video with gemini",
  "gemini image", "gemini video", "veo video", "nano banana", "edit this image with
  gemini", "animate this image", "image to video", "make a video from this photo",
  "sub-billed image/video", "no api credit image/video", or wants free (subscription)
  AI media from the console. Default for generic image→video (free on the sub).
  NOT for: other providers when named (chatgpt-image-gen, gemini-image-generation API,
  grok, modelslab, kling via fal/Replicate — prefer kling for character-consistency
  video work), or when the user explicitly wants API billing.
---

# gemini-web — sub-billed image + video from the console (no API)

Piggybacks the user's logged-in `gemini.google.com` tab in the browser-harness Chrome.
Bills the **Gemini subscription** (Ultra), never the API. Two CLIs on PATH: `gemini-img`,
`gemini-vid`. Outputs land in `~/gemini-web/out/` by default.

## When NOT to use
- The cookie-API (`gemini_webapi`) is **walled for media** (#344 bot-session wall) — text
  works but image/video return "limit resets". Always use these browser-piggyback CLIs for
  media, never the cookie client.
- Another provider was requested → use that provider's skill instead.

## Prerequisites
- `browser-harness` (https://github.com/browser-use/browser-harness) on PATH + a **logged-in**
  `gemini.google.com` tab in the harness Chrome, and `curl` on PATH (video extraction).
  The CLIs self-heal: if no gemini tab is found they create one (`Target.createTarget`).
  If it hits a login wall, stop and ask the user to log in — never type their credentials.
- Runs are **slow** (Veo minutes; images ~30s–4min). Launch long ones in the background so
  they don't hit a foreground command timeout. Space gens out — rapid back-to-back can soft-throttle.

## Usage — 4 modes

```bash
# text -> image  (Nano Banana)
gemini-img "a serene mountain lake at sunrise, photorealistic"

# image -> image  (edit; preserves composition)
gemini-img -i lake.png "make it deep winter, frozen lake, snow"

# text -> video  (Veo, 720p 10s + audio)
gemini-vid "a paper boat sailing down a rain puddle, cinematic"

# image -> video  (animate a still)
gemini-vid -i lake.png "slow push-in, mist drifts, water ripples"
```

Flags: `-p <prefix>` sets the output filename prefix; `-i <path>` gives an input image.
Optional 2nd positional arg = output dir. Each CLI prints **one bare JSON line** with the
saved path(s). PNG for images, mp4 (h264 720p, aac) for video.

Env knobs: `GEMINI_TIMEOUT` (seconds; default 420 img / 900 vid — raise under throttle),
`GEMINI_TARGET` (pin a specific tab targetId, skips discovery), `GEMINI_OUT`, `GEMINI_PREFIX`,
`GEMINI_WIN_DOWNLOADS` (WSL only, optional: Chrome's Windows download dir, e.g.
`/mnt/c/Users/<you>/Downloads`, enabling the Downloads-scrape fallback for video).

Exit codes: 2 = timeout, 3 = limit/refusal served, 4 = no composer/login wall,
5 = video extraction failed, 6 = image upload failed.

## How it works (for debugging)
- **Submit:** fresh chat via the in-app "New chat" (handles the Activity-off "delete this one?"
  confirm dialog); focus the `rich-textarea`; type; **click the Send button** (Enter is unreliable).
- **Image done-signal:** a rendered blob `<img>` (naturalWidth>256) + a Download button.
  Extract via `canvas.toDataURL` (blob is same-origin, canvas untainted). image→image snapshots
  pre-existing blobs (`window.__pre`) before send so it returns only the NEW output, not the input.
- **Video done-signal:** a `<video>` whose src is an https (or blob) URL, **plus** a Download
  button. Do NOT gate on `duration`/`readyState` — Gemini mounts the finished `<video>` at 0x0
  with `preload="metadata"` and never loads it until played, so `readyState` stays 0 and
  `duration` NaN forever while the video is in fact ready. **Host-agnostic extract:** the
  `<video>.currentSrc` is a real https mp4 URL (or capture it from the Network domain on a
  Download click). Pull the browser's cookies via CDP `Storage.getCookies`, write a Netscape jar,
  and `curl -L` the URL **host-side** — bytes travel over HTTPS to the harness host, no shared
  filesystem. Optional fallback: Windows Downloads scrape, WSL only, off unless
  `GEMINI_WIN_DOWNLOADS` points at the Chrome download dir.
- **Image upload (image→image / image→video):** HOST-AGNOSTIC byte-injection (`inject_file`) —
  no `/mnt/c`. Open "Upload & tools" → **real mouse-click** "Upload files" (`click_at_xy` at its
  rect; synthetic `.click()` doesn't fire Angular menu items) with the native chooser intercepted
  (`Page.setInterceptFileChooserDialog`) → **push the file's base64 into the page over CDP** in
  ~24K chunks → reconstruct a `File` and set `input.files` via `DataTransfer`. The wrapper passes
  `GEMINI_INPUT_PATH` (a local file); the driver reads + pushes the bytes.

## Host-agnostic by design
All four modes push every byte over the CDP/HTTPS channel, never a shared filesystem. The same
code therefore works whether the harness drives a Chrome on the same machine or a remote one
(e.g. over an SSH/VPN tunnel) — no `/mnt/c` staging, no cookie transplant. Any agent or shell
can use it: the CLIs are the whole interface.

Install — symlink the two CLIs onto PATH from wherever you cloned the skill:
`ln -sf "$PWD/scripts/gemini-"{img,vid} ~/bin/`

## Gotchas
- **Upload menu is SHADOW DOM + foreground-only.** Gemini's "Upload & tools" menu items render
  inside shadow roots (plain `querySelectorAll` finds nothing — walk `shadowRoot`s), AND the CDK
  overlay only paints while `document.visibilityState === 'visible'`. In a hidden tab the button
  reports `aria-expanded="true"` but **no menu items exist in the DOM** — that is what surfaces as
  `upload failed: menu-item-not-found`. `Target.activateTarget` alone is not enough; both drivers
  now `Page.bringToFront` and then poll `visibilityState` until visible.
- **Match the gemini tab by URL prefix, not substring.** Google's cookie-rotation page
  `accounts.google.com/RotateCookiesPage?...&origin=https%3A%2F%2Fgemini.google.com` carries
  `gemini.google.com` inside a query param, so a substring test matches it — the driver would then
  drive, or *close*, the wrong target. Test `url.startswith("https://gemini.google.com/")`.
- **Give the upload thumbnail ~90s.** A ~1MB PNG pushed in 24K CDP chunks routinely renders its
  composer thumbnail well past 30s; too short a wait reports `no-thumbnail` while the upload is
  visibly fine on screen.
- **Never `goto_url()`/reload then `js()`** in the drivers — a freshly-navigated target's
  `Runtime.evaluate` hangs. Operate on an already-loaded tab; new chat is an SPA click.
- Don't navigate the working tab to Settings/Usage pages mid-session — degrades it
  ("Couldn't connect"); use a fresh tab.
- Tier check: the account badge (sidebar) is authoritative, not `list_models()` (shows only basic
  models on any tier). Live usage limits page: `gemini.google.com/usage`.

## Files
- CLIs: `scripts/gemini-img`, `scripts/gemini-vid` (symlink these onto PATH)
- Drivers (run inside `browser-harness -c`): `scripts/driver_img.py`, `scripts/driver_vid.py`
- Diagnostics (cookie-API path only, not used by the CLIs):
  - `scripts/pull_cookies.py` — refresh `~/gemini-web/cookies.json` from the logged-in harness
    Chrome (run inside `browser-harness -c "exec(open(...).read())"`)
  - `scripts/diagnose_cookie_api.py` — check cookie auth (text → PONG) and whether media is
    still bot-walled (#344); run with `~/gemini-web/bin/python` (venv has `gemini_webapi`)
