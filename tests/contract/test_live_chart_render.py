# tests/contract/test_live_chart_render.py
"""Run manually: pytest -m contract tests/contract/test_live_chart_render.py -v
Hits stockanalysis.com live (keyless) and renders a real chart."""
import pytest

from src.chart import fetch_chart_png
from src.source.base import Candidate

pytestmark = pytest.mark.contract


def test_live_render_is_a_real_png():
    c = Candidate("AAPL", "Apple Inc.", "NASDAQ", 0, 0, 0, 0, "EQUITY")
    png = fetch_chart_png(c)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"   # PNG magic bytes
    assert len(png) > 10_000                  # a real chart, not an error blob
