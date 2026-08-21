"""Vercel serverless entry point.

Vercel routes /api/* to this function, so the ASGI app it serves must expose the
endpoints at the ROOT of the function - the /api prefix is added by the platform,
not by us. `_routes` is the un-prefixed application.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arbitrage.web.api import _routes as app  # noqa: E402

__all__ = ["app"]
