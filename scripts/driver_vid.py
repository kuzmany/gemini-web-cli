# Runs INSIDE `browser-harness -c`. Drives the real logged-in gemini.google.com tab to
# generate a VIDEO (Veo) on the Gemini subscription, then saves the mp4 to disk.
# Live-tested 2026-07-15: text->video AND image->video work (720p 10s + audio).
# Extraction is HOST-AGNOSTIC: resolve the real mp4 URL (the <video> currentSrc is a normal
# https URL, or capture it from the Network domain on Download) and fetch it host-side with
# curl + the browser's cookies. Works whether Chrome is local or remote (bytes over HTTPS,
# no shared filesystem). OPTIONAL FALLBACK = Windows Downloads scrape (WSL only, opt-in).
import os, json, time, base64, glob, pathlib, shutil, subprocess, tempfile

PROMPT   = os.environ["GEMINI_PROMPT"]
OUT      = os.path.expanduser(os.environ.get("GEMINI_OUT", "~/gemini-web/out"))
PREFIX   = os.environ.get("GEMINI_PREFIX", "vid")
TIMEOUT  = float(os.environ.get("GEMINI_TIMEOUT", "900"))          # Veo is slow; +throttle
DLDIR    = os.environ.get("GEMINI_WIN_DOWNLOADS", "")            # optional WSL-only fallback; see README
pathlib.Path(OUT).mkdir(parents=True, exist_ok=True)

def out(obj): print("RESULT " + json.dumps(obj))
def log(*a): print("[vid]", *a)

def _jss(expr, tries=5):
    # js() with retry — the CDP channel occasionally times out a call under load / over a tunnel.
    for _ in range(tries):
        try: return js(expr)
        except Exception: wait(0.6)
    raise RuntimeError("js retry exhausted")

def inject_file(path):
    """Upload a local file into Gemini WITHOUT a shared filesystem: push the bytes over CDP
    (chunked + retry) and set input.files via DataTransfer. Host-agnostic (local or remote Chrome)."""
    ext = path.rsplit('.', 1)[-1].lower()
    mime = {'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','webp':'image/webp','gif':'image/gif'}.get(ext, 'image/png')
    b64 = base64.b64encode(open(os.path.expanduser(path), 'rb').read()).decode()
    for _ in range(20):
        if _jss('!!document.querySelector(\'button[aria-label*="Upload & tools" i]\')'): break
        wait(0.5)
    wait(2.0)
    # Gemini renders the menu items inside SHADOW DOM — walk shadow roots (querySelectorAll misses them).
    FIND = '''(() => { function walk(root,out){ for(const el of root.querySelectorAll('*')){ if((el.textContent||'').trim()==='Upload files'){const r=el.getBoundingClientRect(); if(r.width>4&&r.height>4) out.push(r);} if(el.shadowRoot) walk(el.shadowRoot,out);} } const out=[]; walk(document,out); let bx=null,ba=0; for(const r of out){const a=r.width*r.height; if(a>ba){ba=a;bx=r;}} if(!bx)return null; return JSON.stringify({x:Math.round(bx.x+bx.width/2), y:Math.round(bx.y+bx.height/2)}); })()'''
    ISOPEN = '''(() => { const b=document.querySelector('button[aria-label*="Upload & tools" i]'); return b && b.getAttribute('aria-expanded')==='true' ? 1 : 0; })()'''
    rect = None
    for _attempt in range(6):
        for _ in range(5):
            if int(_jss(ISOPEN)) == 1: break
            _jss('''(() => { const b=document.querySelector('button[aria-label*="Upload & tools" i]'); if(b) b.click(); return 0; })()''')
            wait(1.0)
        wait(1.3)
        for _ in range(8):
            if int(_jss(ISOPEN)) != 1: break
            rect = _jss(FIND)
            if rect and rect != 'null': break
            wait(0.7)
        if rect and rect != 'null': break
        _jss('''(() => { const b=document.querySelector('button[aria-label*="Upload & tools" i]'); if(b && b.getAttribute('aria-expanded')==='true') b.click(); return 0; })()''')
        wait(1.2)
    if not rect or rect == 'null': return 'menu-item-not-found'
    rc = json.loads(rect)
    cdp('Page.enable'); cdp('Page.setInterceptFileChooserDialog', enabled=True)
    click_at_xy(rc['x'], rc['y']); wait(1.5)
    _jss('(window.__up="",0)')
    CH = 24000
    for i in range(0, len(b64), CH):
        _jss('(window.__up+=' + json.dumps(b64[i:i+CH]) + ',0)'); wait(0.03)
    if int(_jss('window.__up.length')) != len(b64):
        cdp('Page.setInterceptFileChooserDialog', enabled=False); return 'push-incomplete'
    inj = _jss('''(() => {
      const inp=document.querySelector('input[type=file]'); if(!inp)return 'no-input';
      const bin=atob(window.__up); const u8=new Uint8Array(bin.length);
      for(let i=0;i<bin.length;i++)u8[i]=bin.charCodeAt(i);
      const f=new File([u8], %s, {type: %s}); const dt=new DataTransfer(); dt.items.add(f);
      inp.files=dt.files; inp.dispatchEvent(new Event('change',{bubbles:true})); return String(inp.files.length);
    })()''' % (json.dumps('input.' + ext), json.dumps(mime)))
    cdp('Page.setInterceptFileChooserDialog', enabled=False)
    if str(inj) in ('no-input', '0'): return 'inject-failed:' + str(inj)
    # 90s, not 30 — a 1MB PNG pushed in 24K chunks lands its thumbnail well past 30s.
    for _ in range(90):
        wait(1.0)
        if int(_jss('[...document.querySelectorAll("img")].filter(i=>i.src.startsWith("blob:")||i.src.startsWith("data:")).length')) >= 1:
            wait(5.0); return 'ok'
    return 'no-thumbnail'

# Match the Gemini app tab by URL PREFIX, not substring: Google's cookie-rotation page
# (accounts.google.com/RotateCookiesPage?...&origin=https%3A%2F%2Fgemini.google.com) contains
# "gemini.google.com" in a query param, so a substring test picks it up and we'd drive — or
# close — the wrong target.
def _is_gemini_url(u):
    return (u or "").startswith("https://gemini.google.com/")

# 1. find + switch to the gemini tab. The daemon's list_tabs is current-window-scoped and
#    flaky across multiple Chrome windows, so poll BOTH list_tabs(include_chrome=True) and
#    the browser-wide Target.getTargets. Accept an explicit GEMINI_TARGET to skip discovery.
gid = os.environ.get("GEMINI_TARGET") or None
if not gid:
    for _ in range(25):
        for t in list_tabs(include_chrome=True):
            if _is_gemini_url(t.get("url")):
                gid = t.get("targetId") or t.get("id"); break
        if gid: break
        for t in cdp("Target.getTargets").get("targetInfos", []):
            if t.get("type") == "page" and _is_gemini_url(t.get("url")):
                gid = t.get("targetId"); break
        if gid: break
        wait(1.0)
if not gid:
    # bh-open tabs can be un-enumerable ("session window"); create one ourselves — a
    # Target.createTarget tab is always enumerable and loads logged-in from the profile.
    gid = cdp("Target.createTarget", url="https://gemini.google.com/app").get("targetId")
    switch_tab(gid)
    for _ in range(20):
        if js('!!document.querySelector("rich-textarea")'): break
        wait(1.0)
else:
    switch_tab(gid)

# Ensure this is the ONLY gemini tab and it's foreground. The Upload menu renders in SHADOW
# DOM which Chrome does NOT paint in a background tab, so a 2nd gemini tab silently breaks upload.
for _t in cdp("Target.getTargets").get("targetInfos", []):
    _tid = _t.get("targetId")
    if _t.get("type") == "page" and _is_gemini_url(_t.get("url")) and _tid != gid:
        try: cdp("Target.closeTarget", {"targetId": _tid})
        except Exception: pass
cdp("Target.activateTarget", targetId=gid)
try: cdp("Page.bringToFront")
except Exception: pass
# activateTarget alone can leave the tab document hidden; the CDK overlay that holds the
# upload menu never paints while hidden, which surfaces later as menu-item-not-found.
for _ in range(10):
    if js('document.visibilityState') == 'visible': break
    try: cdp("Page.bringToFront")
    except Exception: pass
    wait(0.5)

# 2. fresh chat via SPA button (NO goto_url — navigation hangs Runtime.evaluate)
if not js('!!document.querySelector("rich-textarea")'):
    out({"error": "no composer — reopen + log in first"}); raise SystemExit(4)
js('''(() => { const a=document.querySelector('a[aria-label*="New chat" i], button[aria-label*="New chat" i], button[aria-label*="New conversation" i]'); if(a)a.click(); })()''')
wait(1.2)
# Activity-off "delete this one?" confirm blocks the page — click its confirm button.
js('''(() => { const btn=Array.from(document.querySelectorAll('[role=dialog] button, .cdk-overlay-pane button, mat-dialog-container button')).find(b=>/^New chat$/i.test((b.textContent||'').trim())); if(btn){btn.click(); return true;} return false; })()''')
wait(1.5)

# 2b. OPTIONAL image input (image->video: animate a still). GEMINI_INPUT_PATH = a LOCAL file
#     on the harness host. Host-agnostic upload via CDP byte-injection (see inject_file): no
#     shared filesystem, so a local or remote Chrome runs the identical code path.
INPUT_PATH = os.environ.get("GEMINI_INPUT_PATH")
if INPUT_PATH:
    r = inject_file(INPUT_PATH)
    if r != 'ok':
        out({"error": "upload failed: " + r}); raise SystemExit(6)
    log("uploaded input image")

# 3. focus, type, submit via Send button
js('(() => { const rt=document.querySelector("rich-textarea"); const ce=rt&&rt.querySelector(\'[contenteditable="true"]\'); if(ce){ce.focus();} return !!ce; })()')
wait(0.4)
type_text(PROMPT)
wait(0.9)
clicked = js('''(() => {
  let b = document.querySelector('button[aria-label*="Send" i], button[aria-label*="Submit" i]');
  if (!b) b = Array.from(document.querySelectorAll('button:not([disabled])')).find(x => /send|arrow_upward/i.test(x.innerHTML));
  if (b && !b.disabled) { b.click(); return true; }
  return false;
})()''')
if not clicked:
    press_key("Enter")
log("submitted:", PROMPT)
wait(2.0)

# 4. poll until the <video> has a real https src + a Download button exists (Veo renders in minutes).
# Do NOT gate on duration/readyState: Gemini mounts the finished <video> at 0x0 with
# preload="metadata" and never loads it until played, so readyState stays 0 and duration NaN
# forever. The https src in currentSrc is the mp4 we fetch in step 5 — its presence, plus the
# Download button, IS the done-signal.
POLL = '''(() => {
  const v = document.querySelector('video');
  const src = v ? (v.currentSrc || v.src || '') : '';
  const ready = !!(v && (src.indexOf('http') === 0 || src.indexOf('blob:') === 0));
  const dl = document.querySelectorAll('button[aria-label*="Download" i]').length;
  const txt = document.body.innerText || '';
  return JSON.stringify({ready, dl, hasVideo: !!v, srcHead: src.slice(0,20),
    fail: /can'?t create|cannot create|not available|isn'?t available|unable to|content policy|limit/i.test(txt)});
})()'''
deadline, done, info = time.time() + TIMEOUT, False, {}
while time.time() < deadline:
    wait(3.0)
    info = json.loads(js(POLL))
    if info.get("fail") and not info.get("hasVideo"):
        out({"videos": [], "note": "browser showed a refusal/limit message", "state": info}); raise SystemExit(3)
    if info.get("ready") and info.get("dl", 0) >= 1:
        done = True; break
if not done:
    out({"error": "timeout waiting for video", "waited_s": TIMEOUT, "last": info}); raise SystemExit(2)
log("video ready:", info)

# 5. HOST-AGNOSTIC extraction: resolve the real mp4 URL, then fetch it host-side with the
#    browser's cookies (curl). The bytes travel over HTTPS to the harness host, so this works
#    whether Chrome is local or remote (e.g. over a tunnel) — no shared filesystem.
def _video_url():
    # (a) the <video> currentSrc is usually already the downloadable https mp4 URL
    s = _jss('(() => { const v=document.querySelector("video"); const u=v?(v.currentSrc||v.src||""):""; return u.indexOf("http")===0?u:""; })()')
    if s: return s
    # (b) blob src -> click Download and capture the mp4 request URL from the Network domain
    cdp('Network.enable'); drain_events()
    _jss('''(() => { const b=document.querySelector('button[aria-label*="Download" i]'); if(b)b.click(); return 0; })()''')
    for _ in range(20):
        wait(1.0)
        for e in drain_events():
            if e.get('method') in ('Network.responseReceived', 'Network.requestWillBeSent'):
                p = e.get('params', {})
                u = (p.get('response') or {}).get('url', '') or (p.get('request') or {}).get('url', '')
                mime = (p.get('response') or {}).get('mimeType', '')
                if u and ('video' in mime or '.mp4' in u or 'contribution.usercontent' in u or 'videoplayback' in u):
                    return u
    return None

saved = None
url = _video_url()
if url:
    cks = cdp('Storage.getCookies').get('cookies', [])
    jl = ['# Netscape HTTP Cookie File']
    for c in cks:
        dom = c.get('domain', '')
        if 'google.com' not in dom: continue
        inc = 'TRUE' if dom.startswith('.') else 'FALSE'
        sec = 'TRUE' if c.get('secure') else 'FALSE'
        exp = int(c.get('expires') or 0) if (c.get('expires') or 0) > 0 else 2000000000
        jl.append('\t'.join([dom, inc, c.get('path', '/'), sec, str(exp), c.get('name', ''), c.get('value', '')]))
    jf = tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False)
    jf.write('\n'.join(jl) + '\n'); jf.close()
    dst = os.path.join(OUT, "%s_%d.mp4" % (PREFIX, int(time.time())))
    subprocess.run(['curl', '-sL', '-b', jf.name, '-o', dst, url], capture_output=True)
    os.unlink(jf.name)
    if os.path.exists(dst) and os.path.getsize(dst) > 10000:
        saved = dst; log("fetched via cookie-curl", os.path.getsize(dst))

# 5b. OPTIONAL FALLBACK (WSL only, set GEMINI_WIN_DOWNLOADS): scrape the browser's Downloads dir.
if not saved and os.path.isdir(DLDIR):
    start = time.time() - 3
    before = set(glob.glob(os.path.join(DLDIR, "*.mp4")))
    _jss('''(() => { const b=document.querySelector('button[aria-label*="Download" i]'); if(b)b.click(); return 0; })()''')
    for _ in range(40):
        wait(2.0)
        cands = [f for f in glob.glob(os.path.join(DLDIR, "*.mp4"))
                 if (f not in before or os.path.getmtime(f) >= start) and not os.path.exists(f + ".crdownload")]
        if cands:
            newest = max(cands, key=os.path.getmtime); s1 = os.path.getsize(newest); time.sleep(1.5)
            if os.path.getsize(newest) == s1 and s1 > 0:
                dst = os.path.join(OUT, "%s_%d.mp4" % (PREFIX, int(time.time())))
                shutil.copyfile(newest, dst); saved = dst; break

if saved:
    out({"videos": [saved], "bytes": os.path.getsize(saved)})
else:
    out({"error": "no video extracted", "state": info}); raise SystemExit(5)
