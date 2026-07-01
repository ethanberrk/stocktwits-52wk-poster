# tests/contract/test_live_chart_img.py
"""Run manually: CHART_IMG_API_KEY=... pytest -m contract tests/contract/test_live_chart_img.py -v"""
import os
import pytest
from src.chart import fetch_chart_png
from src.source.base import Candidate

pytestmark = pytest.mark.contract

def test_live_chart_is_a_real_png():
    key = os.environ.get("CHART_IMG_API_KEY")
    if not key:
        pytest.skip("CHART_IMG_API_KEY not set")
    c = Candidate("AAPL", "Apple Inc.", "NASDAQ", 0, 0, 0, 0, "EQUITY")
    png = fetch_chart_png(c, key)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"   # PNG magic bytes
    assert len(png) > 10_000                  # a real chart, not an error blob
