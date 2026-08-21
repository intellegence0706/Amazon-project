"""Configuration from a single .env file.

Deliberately one file with one required value. The person setting this up is not
a developer and will not be at a computer for long - every extra step is a place
the handover fails.
"""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def load_env(path=ENV_PATH):
    """Minimal .env reader - avoids a python-dotenv dependency for 15 lines."""
    if not Path(path).exists():
        return {}
    out = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@dataclass
class Settings:
    keepa_api_key: str = ""
    keepa_domain: int = 1            # 1 = amazon.com (US)
    min_roi: float = 30.0
    min_profit: float = 3.00
    max_bsr: int = 250_000
    inbound_cost: float = 0.55       # per-unit shipping into FBA
    prep_cost: float = 0.00
    max_offer_count: int = 15

    @property
    def keepa_configured(self) -> bool:
        return bool(self.keepa_api_key)

    def require_keepa(self):
        if not self.keepa_configured:
            raise MissingKey(
                "No Keepa API key found.\n\n"
                f"Add one to {ENV_PATH}:\n\n"
                "    KEEPA_API_KEY=your_key_here\n\n"
                "Get a key at keepa.com under API. Without it the Amazon side "
                "cannot run and all ROI figures stay modelled."
            )
        return self.keepa_api_key


class MissingKey(RuntimeError):
    pass


def _num(env, key, cast, default):
    try:
        return cast(env.get(key, os.environ.get(key, default)))
    except (TypeError, ValueError):
        return default


def writable() -> bool:
    """False on serverless platforms, where .env cannot be written."""
    return os.environ.get("VERCEL") is None and os.access(ROOT, os.W_OK)


def load(path=ENV_PATH) -> Settings:
    e = load_env(path)
    # Environment wins over .env: on Vercel the key arrives as a project env var.
    get = lambda k, d="": os.environ.get(k) or e.get(k, d)
    return Settings(
        keepa_api_key=get("KEEPA_API_KEY"),
        keepa_domain=_num(e, "KEEPA_DOMAIN", int, 1),
        min_roi=_num(e, "MIN_ROI", float, 30.0),
        min_profit=_num(e, "MIN_PROFIT", float, 3.00),
        max_bsr=_num(e, "MAX_BSR", int, 250_000),
        inbound_cost=_num(e, "INBOUND_COST", float, 0.55),
        prep_cost=_num(e, "PREP_COST", float, 0.00),
        max_offer_count=_num(e, "MAX_OFFER_COUNT", int, 15),
    )
