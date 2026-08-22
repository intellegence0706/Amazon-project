"""Vercel serverless entry point.

Vercel may hand the function either the original request path (/api/stats) or a
rewritten one (/stats), depending on how the rewrite resolves. Rather than
guessing, the routes are mounted at BOTH prefixes, so whichever arrives matches.

A root route is included too: without static output Vercel sends "/" here, and a
bare FastAPI 404 gives no clue what went wrong.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI                                    # noqa: E402
from fastapi.responses import JSONResponse                     # noqa: E402

from arbitrage.web.api import _routes                          # noqa: E402

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Same application, reachable under either prefix.
app.mount("/api", _routes, name="api_prefixed")


@app.get("/", include_in_schema=False)
def _root():
    return JSONResponse({
        "service": "Arbitrage Sourcing Engine API",
        "status": "running",
        "note": ("If you expected the web interface here, the frontend build was "
                 "not served. Check the Vercel project's Output Directory is "
                 "'web/out' and the Framework Preset is 'Other'."),
        "api": "/api/stats",
    })


# Anything not matched above falls through to the un-prefixed routes, so a
# rewritten "/stats" works exactly as "/api/stats" does.
app.mount("/", _routes, name="api_root")
