# Runs INSIDE `browser-harness -c` — harness helpers (js, type_text, ...) are in globals.
# Drives the real logged-in gemini.google.com tab: prompt -> image, saves PNG(s) to disk.
# Uses the genuine browser session (Gemini subscription), sidestepping the #344 cookie-API bot-wall.
import os, json, time, base64, pathlib

PROMPT  = os.environ["GEMINI_PROMPT"]
OUT     = os.path.expanduser(os.environ.get("GEMINI_OUT", "~/gemini-web/out"))
PREFIX  = os.environ.get("GEMINI_PREFIX", "gen")
TIMEOUT = float(os.environ.get("GEMINI_TIMEOUT", "420"))  # gens slow under soft-throttle
pathlib.Path(OUT).mkdir(parents=True, exist_ok=True)

def out(obj):
    print("RESULT " + json.dumps(obj))

def _jss(expr, tries=5):
    # js() with retry — the CDP channel occasionally times out a call under load / over a tunnel.
    for _ in range(tries):
        try: return js(expr)
        except Exception: wait(0.6)
    raise RuntimeError("js retry exhausted")

def inject_file(path):
    """Put a local image into the composer as a synthetic paste event. The bytes travel over CDP
    in 24K chunks (larger messages are refused), so a local or remote Chrome works the same, and
    no upload menu, file chooser or foreground window is needed."""
    ext = path.rsplit('.', 1)[-1].lower()
    mime = {'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','webp':'image/webp','gif':'image/gif'}.get(ext, 'image/png')
    b64 = base64.b64encode(open(os.path.expanduser(path), 'rb').read()).decode()
    _jss("window.__up=''")
    for i in range(0, len(b64), 24000):
        _jss('(window.__up+=' + json.dumps(b64[i:i+24000]) + ',0)')
    r = _jss('''(() => {
      const ce = document.querySelector('rich-textarea [contenteditable="true"]'); if (!ce) return 'no-editor';
      const s = atob(window.__up), a = new Uint8Array(s.length);
      for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i);
      const dt = new DataTransfer(); dt.items.add(new File([a], %s, { type: %s }));
      ce.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
      delete window.__up; return 'ok';
    })()''' % (json.dumps('input.' + ext), json.dumps(mime)))
    if r != 'ok': return r
    # A ~1 MB image can take well over 30 s before its composer thumbnail renders.
    for _ in range(90):
        if int(_jss('[...document.querySelectorAll("img")].filter(i=>i.src.startsWith("blob:")).length')) >= 1:
            wait(3.0); return 'ok'
        wait(1.0)
    return 'no-thumbnail'

# Match the Gemini app tab by URL PREFIX, not substring: Google's cookie-rotation page
# (accounts.google.com/RotateCookiesPage?...&origin=https%3A%2F%2Fgemini.google.com) contains
# "gemini.google.com" in a query param, so a substring test picks it up and we'd drive — or
# close — the wrong target.
def _is_gemini_url(u):
    return (u or "").startswith("https://gemini.google.com/")

# 1. The wrapper (gemini-img) has just opened a fresh gemini.google.com/u/<n>/app tab with
#    bh-open, and browser-harness drives that tab. A fresh tab is already a new chat, so there is
#    no tab discovery, no "New chat" click and no foreground switch (activateTarget is refused in
#    background mode). Other Gemini tabs are left alone, so gemini-vid jobs keep running.
for _ in range(30):
    if js('!!document.querySelector(\'rich-textarea [contenteditable="true"]\')'): break
    wait(1.0)
else:
    out({"error": "no composer; the profile is probably logged out"}); raise SystemExit(4)
ACCOUNT = os.environ.get("GEMINI_ACCOUNT", "").strip().lower()
if ACCOUNT:
    labels = js('JSON.stringify([...document.querySelectorAll(\'[aria-label*="Google Account"]\')].map(e => e.getAttribute("aria-label")))') or "[]"
    if ACCOUNT not in labels.lower():
        out({"error": "signed in as %s, expected %s" % (labels, ACCOUNT)}); raise SystemExit(4)

# 2b. OPTIONAL image input (image->image edit). GEMINI_INPUT_PATH = a LOCAL file on the
#     harness host. Host-agnostic upload via CDP byte-injection (see inject_file): no /mnt/c,
#     no Windows path, so a local or remote Chrome runs the identical code path.
INPUT_PATH = os.environ.get("GEMINI_INPUT_PATH")
if INPUT_PATH:
    r = inject_file(INPUT_PATH)
    if r != 'ok':
        out({"error": "upload failed: " + r}); raise SystemExit(6)

# 3. focus composer, type, submit via the Send button (Enter is unreliable right after reload)
js('(() => { const rt=document.querySelector("rich-textarea"); const ce=rt&&rt.querySelector(\'[contenteditable="true"]\'); if(ce){ce.focus();} return !!ce; })()')
wait(0.4)
type_text(PROMPT)
wait(0.9)
# snapshot pre-existing blob images (e.g. the uploaded input thumbnail) so extraction
# picks only NEW output image(s), never the input.
js('window.__pre = [...document.querySelectorAll("img")].filter(i=>i.src.startsWith("blob:")).map(i=>i.src)')
clicked = js('''(() => {
  let btn = document.querySelector('button[aria-label*="Send" i], button[aria-label*="Submit" i], button[mattooltip*="Send" i]');
  if (!btn) btn = Array.from(document.querySelectorAll('button:not([disabled])')).find(b => /send|arrow_upward/i.test(b.innerHTML));
  if (btn && !btn.disabled) { btn.click(); return true; }
  return false;
})()''')
if not clicked:
    press_key("Enter")
wait(1.0)

# 4. poll until done. Done-signal = a rendered blob image (naturalWidth>256) AND a Download
#    button attached to it. ("Stop response" is NOT reliable — it lingers while Gemini
#    streams a text caption after the image is already complete.)
POLL = '''(() => {
  const imgs = Array.from(document.querySelectorAll('img')).filter(i => i.src.startsWith('blob:') && i.naturalWidth > 256 && !(window.__pre||[]).includes(i.src));
  const dl = document.querySelectorAll('button[aria-label*="Download" i]').length;
  const txt = document.body.innerText || '';
  return JSON.stringify({n: imgs.length, dl: dl, limit: /limit resets|as soon as your limit/i.test(txt)});
})()'''
deadline, done = time.time() + TIMEOUT, False
while time.time() < deadline:
    wait(2.0)
    info = json.loads(js(POLL))
    if info["limit"]:
        out({"images": [], "limit": True, "note": "browser served image-limit message"}); raise SystemExit(3)
    if info["n"] >= 1 and info["dl"] >= 1:
        done = True; break
if not done:
    out({"error": "timeout waiting for image", "waited_s": TIMEOUT}); raise SystemExit(2)

# 5. extract via canvas.toDataURL (robust; blob: is same-origin so canvas is not tainted)
n = int(js('''(() => {
  const imgs = Array.from(document.querySelectorAll('img')).filter(i => i.src.startsWith('blob:') && i.naturalWidth > 256 && !(window.__pre||[]).includes(i.src));
  window.__G = [];
  for (const im of imgs) {
    const c = document.createElement('canvas');
    c.width = im.naturalWidth; c.height = im.naturalHeight;
    c.getContext('2d').drawImage(im, 0, 0);
    window.__G.push(c.toDataURL('image/png').split(',', 2)[1]);
  }
  return window.__G.length;
})()'''))

saved, ts, CH = [], int(time.time()), 500000
for i in range(n):
    L = int(js('window.__G[%d].length' % i))
    parts, off = [], 0
    while off < L:
        parts.append(js('window.__G[%d].slice(%d,%d)' % (i, off, off + CH))); off += CH
    p = os.path.join(OUT, "%s_%d_%d.png" % (PREFIX, ts, i))
    with open(p, "wb") as f:
        f.write(base64.b64decode("".join(parts)))
    saved.append(p)

out({"images": saved, "limit": False, "count": len(saved)})
