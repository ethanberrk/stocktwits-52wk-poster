"""Shared JSON-over-HTTP helper. urllib on purpose (see src/stocktwits.py):
some CDNs 403 the requests TLS fingerprint but pass urllib."""
import json
import time
import urllib.error
import urllib.request

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def get_json(url, opener=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            fh = (opener.open(req, timeout=12) if opener
                  else urllib.request.urlopen(req, timeout=12))
            with fh as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(1.5 * (i + 1)); continue
            return None
        except Exception:
            time.sleep(0.5 * (i + 1))
    return None
