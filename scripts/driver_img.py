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
    """Upload a local file into Gemini WITHOUT a shared filesystem: push the bytes over CDP
    (chunked + retry) and set input.files via DataTransfer. Works whether Chrome is local or
    remote over a tunnel, so the driver is host-agnostic (both use the identical path)."""
    ext = path.rsplit('.', 1)[-1].lower()
    mime = {'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','webp':'image/webp','gif':'image/gif'}.get(ext, 'image/png')
    b64 = base64.b64encode(open(os.path.expanduser(path), 'rb').read()).decode()
    # Let the composer settle (new-chat re-renders it), then open "Upload & tools" and find
    # "Upload files". The menu can render its items late or auto-close, so retry the whole
    # open+find a few times. Real click is required (synthetic .click() doesn't fire it).
    for _ in range(20):
        if _jss('!!document.querySelector(\'button[aria-label*="Upload & tools" i]\')'): break
        wait(0.5)
    wait(2.0)
    # find "Upload files" by the LARGEST visible match (getBoundingClientRect size — offsetParent
    # is unreliable for cdk-overlay items during the open animation).
    # Gemini renders the menu items inside SHADOW DOM, so walk shadow roots (querySelectorAll
    # alone misses them). Pick the largest visible "Upload files" match (the clickable row).
    FIND = '''(() => { function walk(root,out){ for(const el of root.querySelectorAll('*')){ if((el.textContent||'').trim()==='Upload files'){const r=el.getBoundingClientRect(); if(r.width>4&&r.height>4) out.push(r);} if(el.shadowRoot) walk(el.shadowRoot,out);} } const out=[]; walk(document,out); let bx=null,ba=0; for(const r of out){const a=r.width*r.height; if(a>ba){ba=a;bx=r;}} if(!bx)return null; return JSON.stringify({x:Math.round(bx.x+bx.width/2), y:Math.round(bx.y+bx.height/2)}); })()'''
    ISOPEN = '''(() => { const b=document.querySelector('button[aria-label*="Upload & tools" i]'); return b && b.getAttribute('aria-expanded')==='true' ? 1 : 0; })()'''
    rect = None
    for _attempt in range(6):
        for _ in range(5):
            if int(_jss(ISOPEN)) == 1: break
            _jss('''(() => { const b=document.querySelector('button[aria-label*="Upload & tools" i]'); if(b) b.click(); return 0; })()''')
            wait(1.0)
        wait(1.3)  # open animation + item render
        for _ in range(8):
            if int(_jss(ISOPEN)) != 1: break   # menu closed -> reopen (outer loop)
            rect = _jss(FIND)
            if rect and rect != 'null': break
            wait(0.7)
        if rect and rect != 'null': break
        _jss('''(() => { const b=document.querySelector('button[aria-label*="Upload & tools" i]'); if(b && b.getAttribute('aria-expanded')==='true') b.click(); return 0; })()''')  # close + retry
        wait(1.2)
    if not rect or rect == 'null':
        try:
            capture_screenshot('/tmp/gw_inject_fail.png')
            dbg = _jss('''(() => { const b=document.querySelector('button[aria-label*="Upload & tools" i]'); return JSON.stringify({url:document.location.href.slice(0,45), exp:b?b.getAttribute('aria-expanded'):'no-btn', uf:[...document.querySelectorAll('*')].filter(e=>e.offsetParent!==null&&(e.textContent||'').trim()==='Upload files').length, allUf:[...document.querySelectorAll('*')].filter(e=>(e.textContent||'').trim()==='Upload files').length}); })()''')
        except Exception as e: dbg = 'dbg-err:' + str(e)[:40]
        return 'menu-item-not-found ' + str(dbg)
    rc = json.loads(rect)
    cdp('Page.enable'); cdp('Page.setInterceptFileChooserDialog', enabled=True)
    click_at_xy(rc['x'], rc['y']); wait(1.5)
    # push base64 in chunks (send limit ~50K; return 0 so the growing string isn't re-serialized)
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

# 1. find + switch to the gemini tab. list_tabs is current-window-scoped and flaky across
#    multiple Chrome windows, so poll both it and the browser-wide Target.getTargets.
#    Accept an explicit GEMINI_TARGET to skip discovery.
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

# 2. fresh chat — WITHOUT a page reload. goto_url()/navigation makes the target's
#    Runtime.evaluate hang (stale execution context), so click the in-app "New chat"
#    button instead (SPA route change keeps the CDP session alive). Tab is already on
#    gemini.google.com/app (opened via bh-open).
if not js('!!document.querySelector("rich-textarea")'):
    out({"error": "no composer — reopen + log in: bh-open 'https://gemini.google.com/app' gemini"}); raise SystemExit(4)
js('''(() => { const a=document.querySelector('a[aria-label*="New chat" i], button[aria-label*="New chat" i], button[aria-label*="New conversation" i]'); if(a)a.click(); })()''')
wait(1.2)
# When Gemini Apps Activity is OFF, "New chat" pops a "delete this one?" confirm that
# blocks the page — click its confirm button (a <button> reading "New chat" in the dialog).
js('''(() => { const btn=Array.from(document.querySelectorAll('[role=dialog] button, .cdk-overlay-pane button, mat-dialog-container button')).find(b=>/^New chat$/i.test((b.textContent||'').trim())); if(btn){btn.click(); return true;} return false; })()''')
wait(1.5)

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
