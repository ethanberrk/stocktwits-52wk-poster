"""Stocktwits symbology: cashtag format mapping and pre-post validation."""
import urllib.error
import urllib.request

import config
from src.source.base import Candidate

# urllib on purpose: Stocktwits' CDN bot-blocks the `requests` library's TLS
# fingerprint (403 regardless of headers) but passes urllib — verified live
# 2026-07-02, and the WSJ prototype relied on the same behavior.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

def st_symbol(ticker: str) -> str:
    """Yahoo ticker -> Stocktwits symbol. Yahoo spells share classes with a
    dash (BRK-B); Stocktwits uses a dot (BRK.B). A dash cashtag would never
    land in the ticker's stream."""
    return ticker.replace("-", ".")

def symbol_exists(candidate: Candidate, timeout: int = 15) -> bool:
    """Pre-post cashtag validation against Stocktwits' public symbol endpoint.

    False only on a definitive 404 (symbol genuinely not on Stocktwits).
    Indeterminate failures (403 bot-walls on datacenter IPs, timeouts, 5xx)
    return True: the cost of posting unverified is at worst an unlinked
    cashtag, while failing closed would silence all posting whenever the
    CDN blocks the runner's IP."""
    url = config.STOCKTWITS_SYMBOL_URL.format(symbol=st_symbol(candidate.ticker))
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        print(f"stocktwits symbol check indeterminate for "
              f"{candidate.ticker} (HTTP {e.code}); allowing")
        return True
    except (urllib.error.URLError, OSError) as e:
        print(f"stocktwits symbol check indeterminate for "
              f"{candidate.ticker} ({e}); allowing")
        return True
