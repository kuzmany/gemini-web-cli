# Pull Gemini auth cookies from the logged-in harness Chrome via CDP (httpOnly cookies —
# document.cookie can't see them). Writes ~/gemini-web/cookies.json (600) for the
# cookie-API path (diagnose_cookie_api.py). Re-run when cookies expire.
# Run INSIDE the harness:  browser-harness -c "exec(open('<this file>').read())"
import json, os, stat

want = {"__Secure-1PSID", "__Secure-1PSIDTS"}
res = cdp("Storage.getCookies")  # browser-wide, includes httpOnly
cookies = res.get("cookies", [])
found = {}
for c in cookies:
    dom = c.get("domain", "")
    if c.get("name") in want and dom.endswith("google.com"):
        # prefer the account-level .google.com cookie
        found.setdefault(c["name"], c["value"])

out = os.path.expanduser("~/gemini-web/cookies.json")
with open(out, "w") as f:
    json.dump(found, f)
os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)  # 600

def mask(v):
    return f"len={len(v)} …{v[-4:]}" if v else "MISSING"

print("PSID   :", mask(found.get("__Secure-1PSID", "")))
print("PSIDTS :", mask(found.get("__Secure-1PSIDTS", "")))
print("total google cookies scanned:", sum(1 for c in cookies if c.get("domain","").endswith("google.com")))
print("written:", out)
