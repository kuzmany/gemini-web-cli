# Diagnostic for the COOKIE-API path (gemini_webapi) — NOT used by gemini-img/gemini-vid.
# Confirms auth (text should return PONG) and shows whether image-gen is still bot-walled
# (#344: "limit resets" on the cookie session while the real browser generates fine).
# Run:  ~/gemini-web/bin/python diagnose_cookie_api.py   (venv has gemini_webapi installed)
# Needs ~/gemini-web/cookies.json — refresh it with pull_cookies.py if expired (exit 4 / 401).
import asyncio, json, os, pathlib
from gemini_webapi import GeminiClient

CK = json.load(open(os.path.expanduser("~/gemini-web/cookies.json")))
OUT = os.path.expanduser("~/gemini-web/out")
pathlib.Path(OUT).mkdir(parents=True, exist_ok=True)
os.environ.setdefault("GEMINI_COOKIE_PATH", os.path.expanduser("~/gemini-web/.cache"))

async def main():
    client = GeminiClient(CK["__Secure-1PSID"], CK.get("__Secure-1PSIDTS", ""), proxy=None)
    await client.init(timeout=60, auto_close=False, auto_refresh=True)
    print("[init] ok")

    # 1) cheap text auth check
    r = await client.generate_content("Reply with exactly: PONG")
    print("[text]", (r.text or "")[:80].replace("\n", " "))

    # 2) image gen
    r = await client.generate_content("Generate a picture of a red cat sitting on a blue chair")
    print("[image] images returned:", len(r.images))
    for i, img in enumerate(r.images):
        saved = await img.save(path=OUT + "/", filename=f"redcat_{i}.png", verbose=False)
        print("   saved:", saved)
    if not r.images:
        print("[image] no images; model text:", (r.text or "")[:120].replace("\n", " "))

asyncio.run(main())
