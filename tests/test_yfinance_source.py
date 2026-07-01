import pytest
from src.source.base import SourceError
from src.source.yfinance_source import YFinanceSource

def good_row(sym, day_high, wk_high):
    return {"symbol": sym, "shortName": f"{sym} Inc", "exchange": "NYQ",
            "quoteType": "EQUITY", "regularMarketPrice": day_high - 1,
            "regularMarketChangePercent": 1.0, "regularMarketDayHigh": day_high,
            "fiftyTwoWeekHigh": wk_high, "marketCap": 5e9}

def test_fetch_filters_to_new_highs(monkeypatch):
    src = YFinanceSource()
    rows = [good_row("HI", 101.0, 101.0),      # at 52wk high -> candidate
            good_row("LO", 90.0, 101.0)]       # not at high -> dropped
    monkeypatch.setattr(src, "_screen_rows", lambda: rows)
    got = src.fetch_candidates()
    assert [c.ticker for c in got] == ["HI"]

def test_fetch_raises_source_error_on_empty_screen(monkeypatch):
    src = YFinanceSource()
    monkeypatch.setattr(src, "_screen_rows", lambda: [])
    with pytest.raises(SourceError):
        src.fetch_candidates()

def test_zero_highs_from_nonempty_screen_is_fine(monkeypatch):
    src = YFinanceSource()
    monkeypatch.setattr(src, "_screen_rows", lambda: [good_row("LO", 90.0, 101.0)])
    assert src.fetch_candidates() == []
