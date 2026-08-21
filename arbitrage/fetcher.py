"""Every outbound request goes through a Fetcher.

The point is vendor independence: swapping DirectFetcher for ScraperAPIFetcher is
a config change, not a rewrite, and retailers can be routed individually so you
only pay for the ones that actually block you.
"""
import gzip
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class FetchError(Exception):
    def __init__(self, url, status=None, reason=""):
        self.url, self.status, self.reason = url, status, reason
        super().__init__(f"{status or 'ERR'} {reason} <- {url}")


class DirectFetcher:
    """Plain HTTP. Free. Works for tier-1 and tier-2 retailers."""

    name = "direct"

    def __init__(self, delay=0.7, timeout=20, retries=2):
        self.delay, self.timeout, self.retries = delay, timeout, retries
        self._last = 0.0

    def _throttle(self):
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def get(self, url, headers=None):
        hdrs = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip"}
        hdrs.update(headers or {})
        last = None
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                req = urllib.request.Request(url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = r.read()
                    if raw[:2] == b"\x1f\x8b":
                        raw = gzip.decompress(raw)
                    return raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                last = FetchError(url, e.code, e.reason)
                if e.code in (403, 429, 503) and attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise last
            except Exception as e:                      # noqa: BLE001
                last = FetchError(url, None, type(e).__name__)
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise last
        raise last


class ScraperAPIFetcher(DirectFetcher):
    """Drop-in for tier-4 retailers behind Akamai / PerimeterX.

    Not wired to a vendor account yet - it becomes live the moment an API key
    exists. Deliberately subclasses DirectFetcher so behaviour stays identical.
    """

    name = "scraperapi"
    ENDPOINT = "https://api.scraperapi.com/"

    def __init__(self, api_key, render=False, **kw):
        super().__init__(**kw)
        self.api_key, self.render = api_key, render

    def get(self, url, headers=None):
        q = urllib.parse.urlencode({
            "api_key": self.api_key,
            "url": url,
            # rendering costs 5-10x credits - keep it off unless a site demands it
            "render": "true" if self.render else "false",
        })
        return super().get(f"{self.ENDPOINT}?{q}", headers)
