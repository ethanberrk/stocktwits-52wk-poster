import requests

import config
from src.source.base import Candidate

class ChartError(Exception):
    """Chart service failed for this ticker; skip it this tick (stays eligible)."""

def _request_args(candidate: Candidate, api_key: str) -> tuple[str, dict, dict]:
    symbol = (f"{candidate.exchange}:{candidate.ticker}"
              if candidate.exchange else candidate.ticker)
    # session="regular" drops pre/post-market so the snapshot never freezes an
    # extended-hours "Pre" price line (a real artifact on charts captured in the
    # opening minute). v2 takes these as a POST JSON body, not query params.
    body = {"symbol": symbol, "interval": "1D", "range": "1Y",
            "width": 800, "height": 450, "theme": "light", "session": "regular"}
    return config.CHART_IMG_URL, body, {"x-api-key": api_key}

def fetch_chart_png(candidate: Candidate, api_key: str) -> bytes:
    url, body, headers = _request_args(candidate, api_key)
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise ChartError(f"{candidate.ticker}: {e}") from e
    if resp.status_code != 200:
        raise ChartError(f"{candidate.ticker}: chart-img returned {resp.status_code}")
    return resp.content
