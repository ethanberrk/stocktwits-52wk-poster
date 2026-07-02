import requests

import config
from src.source.base import Candidate

class ChartError(Exception):
    """Chart service failed for this ticker; skip it this tick (stays eligible)."""

def _request_args(candidate: Candidate, api_key: str) -> tuple[str, dict, dict]:
    symbol = (f"{candidate.exchange}:{candidate.ticker}"
              if candidate.exchange else candidate.ticker)
    params = {"symbol": symbol, "interval": "1D", "range": "1Y",
              "width": 800, "height": 450, "theme": "light"}
    return config.CHART_IMG_URL, params, {"x-api-key": api_key}

def fetch_chart_png(candidate: Candidate, api_key: str) -> bytes:
    url, params, headers = _request_args(candidate, api_key)
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise ChartError(f"{candidate.ticker}: {e}") from e
    if resp.status_code != 200:
        raise ChartError(f"{candidate.ticker}: chart-img returned {resp.status_code}")
    return resp.content
