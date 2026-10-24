# One step against gemini.google.com, run inside browser-harness in a tab that bh-open has just
# opened (see gemini-vid). A fresh tab per step is deliberate: an open Gemini tab never shows a
# finished video until it is reloaded, and a freshly opened tab is already loaded.
#
# GV_MODE=submit  GV_PROMPT, optional GV_IMAGE (jpeg/png path), optional GV_ACCOUNT (email that must
#                 be the signed-in account) -> prints "GV CHAT <url>"
# GV_MODE=fetch   tab is the chat url; GV_JAR = cookie-jar path to write
#                 -> "GV URL <video url>" | "GV PENDING" | "GV FAILED <reply text>"
# Any problem prints "GV ERROR <code> <text>"; codes follow the CLI exit codes (4 login/account,
# 6 upload, 5 extraction).
#
# Images go in as a synthetic paste event on the composer: no upload menu, no file chooser and no
# foreground window needed (the upload menu only renders while the tab is visible).
import base64, json, os, time


def say(kind, value=""):
    print(f"GV {kind} {value}".strip(), flush=True)


def stop(code, text):
    say("ERROR", f"{code} {text}")
    raise SystemExit


def wait(expr, seconds):
    for _ in range(int(seconds)):
        if js(expr):
            return True
        time.sleep(1)
    return False


EDITOR = "document.querySelector('rich-textarea [contenteditable=\"true\"]')"
mode = os.environ["GV_MODE"]

if mode == "submit":
    if not wait(f"!!{EDITOR}", 30):
        stop(4, "no Gemini composer; the profile is probably logged out")
    account = os.environ.get("GV_ACCOUNT", "").strip().lower()
    if account:
        labels = js("JSON.stringify([...document.querySelectorAll('[aria-label*=\"Google Account\"]')].map(e => e.getAttribute('aria-label')))") or "[]"
        if account not in labels.lower():
            stop(4, f"signed in as {labels}, expected {account}")
    image = os.environ.get("GV_IMAGE", "")
    if image:
        mime = "image/png" if image.lower().endswith(".png") else "image/jpeg"
        data = base64.b64encode(open(image, "rb").read()).decode()
        js("window.__gv=''")
        for i in range(0, len(data), 24000):  # larger CDP messages are refused
            js(f"window.__gv+={data[i:i + 24000]!r}")
        js(f"""(() => {{
          const s = atob(window.__gv), a = new Uint8Array(s.length);
          for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i);
          const dt = new DataTransfer();
          dt.items.add(new File([a], {json.dumps(os.path.basename(image))}, {{ type: {json.dumps(mime)} }}));
          {EDITOR}.dispatchEvent(new ClipboardEvent('paste', {{ clipboardData: dt, bubbles: true, cancelable: true }}));
          delete window.__gv;
        }})()""")
        if not wait("document.querySelectorAll('img[src^=\"blob:\"]').length > 0", 90):
            stop(6, "the pasted image did not show up in the composer")
    js(f"(() => {{ const ce = {EDITOR}; ce.focus(); document.execCommand('insertText', false, {json.dumps(os.environ['GV_PROMPT'])}); }})()")
    # The send button stays disabled until the image has finished uploading.
    send = "document.querySelector('button[aria-label*=\"Send\" i]:not([disabled]):not([aria-disabled=\"true\"])')"
    if not wait(f"!!{send}", 120):
        stop(6, "the send button stayed disabled")
    js(f"{send}.click()")
    if not wait("/\\/app\\/[0-9a-f]{8,}/.test(location.pathname)", 60):
        stop(5, "Gemini did not open a chat after sending")
    say("CHAT", js("location.href"))

elif mode == "fetch":
    wait("!!document.querySelector('model-response')", 30)
    time.sleep(3)
    url = js("(() => { const v = document.querySelector('model-response video'); const u = v && (v.currentSrc || v.src); return u && u.startsWith('http') ? u : ''; })()")
    text = js("[...document.querySelectorAll('model-response')].map(e => e.innerText).join(' ').slice(-500)") or ""
    if url:
        with open(os.environ["GV_JAR"], "w") as f:
            f.write("# Netscape HTTP Cookie File\n")
            for c in cdp("Storage.getCookies").get("cookies", []):
                expires = str(int(c["expires"])) if c.get("expires", 0) > 0 else "0"
                f.write("\t".join([c["domain"], "TRUE" if c["domain"].startswith(".") else "FALSE", c["path"],
                                   "TRUE" if c["secure"] else "FALSE", expires, c["name"], c["value"]]) + "\n")
        os.chmod(os.environ["GV_JAR"], 0o600)
        say("URL", url)
    elif "generating" in text.lower() or not text.strip():
        say("PENDING")
    else:
        say("FAILED", " ".join(text.split())[:400])
