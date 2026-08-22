"""Check everything a deployment needs, before deploying.

Six things have to be right at once. Finding out which one is wrong from a
Vercel build log is slow; finding out here takes two seconds.
"""
import os
import shutil
from pathlib import Path

from . import config, db
from .verify import FAIL, PASS, SKIP, WARN, Check

ROOT = Path(__file__).resolve().parent.parent


def run():
    checks, add = [], lambda *a, **k: None
    out = []
    add = lambda name, status, detail="", fix="": out.append(Check(name, status, detail, fix))

    # 1 -- connection string ------------------------------------------------
    url = db.database_url()
    if not url:
        add("DATABASE_URL", FAIL, "not set",
            "export DATABASE_URL='postgresql://postgres.[REF]:[PW]"
            "@aws-0-[REGION].pooler.supabase.com:6543/postgres'")
        return out
    if not db.is_postgres():
        add("DATABASE_URL", FAIL, "set, but not a Postgres URL",
            "It must begin with postgresql:// — copy it from Supabase.")
        return out
    # Pasting the example verbatim is the single most common setup mistake.
    PLACEHOLDERS = ("YOUR_REAL_PASSWORD", "YOUR-PASSWORD", "[YOUR-PASSWORD]",
                    "YOURPASSWORD", "PASSWORD", "your_password", "<password>")
    userinfo = url.split("@")[0]
    if any(ph in userinfo for ph in PLACEHOLDERS):
        add("DATABASE_URL", FAIL, "password is still the example placeholder",
            "Replace it with your real Supabase database password. "
            "Forgot it? Supabase → Settings → Database → Reset database password.")
        return out
    if "[" in userinfo or "]" in userinfo:
        add("DATABASE_URL", FAIL, "square brackets left in the string",
            "Remove the [ ] around the password — they are placeholder markers, "
            "not part of the value.")
        return out

    add("DATABASE_URL", PASS, f"…@{url.split('@')[-1][:46]}")

    # 2 -- pooler, not direct ----------------------------------------------
    if db.pooled():
        add("Transaction pooler", PASS, "port 6543 — correct for serverless")
    else:
        add("Transaction pooler", FAIL, "direct connection (port 5432)",
            "Use the 'Transaction pooler' string from Supabase → Settings → "
            "Database. A direct connection runs out of slots under load.")

    # 3 -- can we actually reach it ----------------------------------------
    try:
        conn = db.init()
        add("Supabase reachable", PASS, "connected, schema created")
    except Exception as e:
        raw = str(e)
        msg = raw.split("\n")[0][:80]
        if "password authentication failed" in raw:
            add("Supabase reachable", FAIL,
                "reached the server, but the password was rejected",
                "The network, region and port are all correct — only the password "
                "is wrong. Supabase → Settings → Database → Reset database password, "
                "then use the new one. Avoid @ : / # in it.")
        elif "does not exist" in raw or "Name or service not known" in raw:
            add("Supabase reachable", FAIL, msg,
                "Check the region in the hostname matches your project.")
        elif "timeout" in raw.lower():
            add("Supabase reachable", FAIL, "connection timed out",
                "The project may be paused — free-tier projects pause after "
                "~1 week idle. Open the Supabase dashboard to resume it.")
        else:
            add("Supabase reachable", FAIL, msg,
                "Check the password, and that the project is not paused.")
        return out

    # 4 -- is there data --------------------------------------------------
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        r = conn.execute("SELECT COUNT(*) AS c FROM retailers").fetchone()["c"]
        if n == 0:
            add("Data uploaded", FAIL, "database is empty",
                "Run: python3 -m arbitrage.cli migrate")
        else:
            add("Data uploaded", PASS, f"{n:,} products across {r} retailers")
    except Exception as e:
        add("Data uploaded", FAIL, str(e)[:70], "Run: python3 -m arbitrage.cli migrate")

    # 5 -- frontend built --------------------------------------------------
    index = ROOT / "web" / "out" / "index.html"
    add("Frontend built", PASS if index.exists() else FAIL,
        "web/out/index.html present" if index.exists() else "web/out is missing",
        "" if index.exists() else "cd web && npm install && npm run build")

    # 6 -- deployment files ------------------------------------------------
    missing = [f for f in ("vercel.json", "requirements.txt", "api/index.py")
               if not (ROOT / f).exists()]
    add("Deployment files", PASS if not missing else FAIL,
        "vercel.json, requirements.txt, api/index.py" if not missing
        else f"missing: {', '.join(missing)}")

    # 7 -- Keepa key (optional) --------------------------------------------
    s = config.load()
    add("Keepa key", PASS if s.keepa_configured else WARN,
        "configured" if s.keepa_configured else "not set — figures stay modelled",
        "" if s.keepa_configured
        else "Optional. Set KEEPA_API_KEY in Vercel env vars for real Amazon data.")

    # 8 -- vercel cli ------------------------------------------------------
    has = shutil.which("vercel")
    add("Vercel CLI", PASS if has else SKIP,
        has or "not installed",
        "" if has else "npm i -g vercel  (or deploy by connecting the git repo)")

    return out


def report(checks):
    w = max(len(c.name) for c in checks)
    lines = ["", "  DEPLOYMENT PREFLIGHT", "  " + "─" * (w + 56)]
    for c in checks:
        lines.append(f"  {c.icon} {c.name:<{w}}  {c.status:<4} {c.detail}")
        if c.fix:
            lines.append(f"    {'':<{w}}       → {c.fix}")
    n = sum(1 for c in checks if c.status == FAIL)
    lines += ["  " + "─" * (w + 56)]
    lines.append("  NOT READY — fix the items above.\n" if n
                 else "  READY TO DEPLOY.  Run:  vercel\n")
    return "\n".join(lines)
