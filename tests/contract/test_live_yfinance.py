# tests/contract/test_live_yfinance.py
"""Run manually on a market day: pytest -m contract tests/contract/test_live_yfinance.py -v"""
import pytest
from src.source.yfinance_source import YFinanceSource

pytestmark = pytest.mark.contract

def test_screen_returns_plausible_universe_and_highs():
    src = YFinanceSource()
    rows = src._screen_rows()
    # coverage check for the documented pagination-cap limitation
    assert len(rows) > 500, f"screen coverage suspiciously low: {len(rows)} rows"
    cands = src.fetch_candidates()
    assert 0 <= len(cands) < 500
    if cands:
        c = cands[0]
        assert c.ticker and c.market_cap >= 1e9 and c.week52_high > 0
        print(f"\n{len(rows)} screened, {len(cands)} on today's 52wk-high list; "
              f"top: {[x.ticker for x in cands[:10]]}")
