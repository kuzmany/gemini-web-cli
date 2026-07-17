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

# image -> video  (animate a still)
gemini-vid -i lake.png "slow push-in, mist drifts, water ripples"
```

Each command prints one bare JSON line with the saved path — easy to pipe or hand to an
agent:

```json
{"videos": ["/home/you/gemini-web/out/vid_1784288370.mp4"], "bytes": 2537843}
```

## Requirements

- [browser-harness](https://github.com/browser-use/browser-harness) on your PATH.
- A Chrome driven by that harness, with a **logged-in** `gemini.google.com` tab. If the
  drivers find no tab they open one; if that hits a login wall, log in yourself.
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
| `GEMINI_TIMEOUT` | seconds to wait; default 420 (image) / 900 (video). Raise under throttle |
| `GEMINI_TARGET` | pin an exact tab targetId, skipping discovery |
| `GEMINI_WIN_DOWNLOADS` | WSL only, optional. Chrome's Windows download dir (e.g. `/mnt/c/Users/<you>/Downloads`), enabling the Downloads-scrape fallback for video |

Exit codes: `2` timeout, `3` limit or refusal served by Gemini, `4` no composer / login
wall, `5` video extraction failed, `6` image upload failed.

## How it works

Everything crosses the CDP/HTTPS channel, so it behaves identically whether Chrome runs on
the same machine or a remote one over a tunnel — there is no shared-filesystem step.

- **Submit** — open a fresh chat via the in-app "New chat" button (an SPA click; never
  navigate, see below), focus the `rich-textarea`, type, click Send.
- **Upload** (image→image, image→video) — open "Upload & tools", real-mouse-click "Upload
  files" with the native file chooser intercepted, then push the file's base64 into the page
  in ~24K chunks and reconstruct a `File` via `DataTransfer`. No file ever touches a shared
  disk.
- **Images out** — a rendered blob `<img>` plus a Download button is the done-signal; the
  bytes come back through `canvas.toDataURL` (the blob is same-origin, so the canvas is not
  tainted).
- **Video out** — the finished `<video>`'s `currentSrc` is a normal https mp4 URL. Cookies
  are read via CDP `Storage.getCookies` into a Netscape jar, and `curl` fetches the URL from
  the host running the CLI.

## Gotchas worth knowing

These are load-bearing; each one cost a debugging session.

- **The tab must be genuinely visible.** Gemini's upload menu lives in shadow DOM inside a
  CDK overlay that only paints while `document.visibilityState === 'visible'`. In a hidden
  tab the button will happily report `aria-expanded="true"` while **no menu items exist at
  all**. `Target.activateTarget` is not enough — `Page.bringToFront`, then poll visibility.
- **Never gate video readiness on `duration` or `readyState`.** Gemini mounts the finished
  `<video>` at 0×0 with `preload="metadata"` and never loads it until played, so
  `readyState` stays `0` and `duration` stays `NaN` indefinitely — the video is ready
  regardless. Gate on an https/blob `currentSrc` plus a Download button.
- **Match the tab by URL prefix, not substring.** Google's cookie-rotation page
  (`accounts.google.com/RotateCookiesPage?...&origin=https%3A%2F%2Fgemini.google.com`)
  contains `gemini.google.com` in a query parameter. A substring match will find it and
  drive — or close — the wrong target.
- **Give an upload ~90 seconds.** A 1MB PNG chunked over CDP regularly renders its composer
  thumbnail past the 30s mark.
- **Never navigate, then evaluate.** A freshly navigated target hangs `Runtime.evaluate`.
  Work on an already-loaded tab and switch chats with SPA clicks. Likewise, don't send the
  working tab to Settings/Usage mid-session — it degrades into "Couldn't connect".
- Runs are slow (images ~30s–4min, Veo minutes) and back-to-back generations can
  soft-throttle. Launch them in the background and space them out.

## Scripts

- `scripts/gemini-img`, `scripts/gemini-vid` — the CLIs (symlink onto PATH).
- `scripts/driver_img.py`, `scripts/driver_vid.py` — drivers, run inside `browser-harness -c`.
- `scripts/pull_cookies.py`, `scripts/diagnose_cookie_api.py` — diagnostics for the
  cookie-API path (`gemini_webapi`). Not used by the CLIs, and note that the cookie API is
  bot-walled for media: text works, image/video return "limit resets". That wall is the
  reason this project drives a real browser instead.

## Notes

This automates *your own* logged-in session against your own subscription, the same actions
you could perform by hand. Google may change the Gemini DOM at any time and break the
selectors — the gotchas above are the usual suspects when it does. Respect Gemini's terms
and rate limits.
