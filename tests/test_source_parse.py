from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.source.base import Candidate
from src.source.yfinance_source import _row_to_candidate

ET = ZoneInfo("America/New_York")
TODAY = date(2026, 7, 1)
# 2026-07-01 14:30 ET, expressed the way Yahoo sends it: epoch seconds
TS_TODAY = int(datetime(2026, 7, 1, 14, 30, tzinfo=ET).timestamp())
TS_YESTERDAY = int(datetime(2026, 6, 30, 15, 59, tzinfo=ET).timestamp())

def row(**over):
    base = {
        "symbol": "AAPL", "shortName": "Apple Inc.", "exchange": "NMS",
        "quoteType": "EQUITY", "regularMarketPrice": 250.0,
        "regularMarketChangePercent": 1.8, "regularMarketDayHigh": 252.0,
        "fiftyTwoWeekHigh": 252.0, "marketCap": 3.9e12,
        "regularMarketTime": TS_TODAY,
    }
    base.update(over)
    return base

def test_new_high_row_parses():
    c = _row_to_candidate(row(), TODAY)
    assert c == Candidate("AAPL", "Apple Inc.", "NASDAQ", 250.0, 1.8,
                          3.9e12, 252.0, "EQUITY")

def test_not_at_high_is_dropped():
    assert _row_to_candidate(row(regularMarketDayHigh=240.0), TODAY) is None

def test_day_cumulative_high_kept_even_after_pullback():
    # broke out earlier today (day high == 52wk high), pulled back to 245
    assert _row_to_candidate(row(regularMarketPrice=245.0), TODAY) is not None

def test_stale_quote_dropped_market_holiday():
    # holiday scenario: gate passes (weekday) but the quote last traded
    # the previous session -> must not post
    assert _row_to_candidate(row(regularMarketTime=TS_YESTERDAY), TODAY) is None

def test_missing_quote_time_dropped():
    r = row(); del r["regularMarketTime"]
    assert _row_to_candidate(r, TODAY) is None
    assert _row_to_candidate(row(regularMarketTime=None), TODAY) is None

def test_non_equity_dropped():
    assert _row_to_candidate(row(quoteType="ETF"), TODAY) is None

def test_excluded_name_dropped():
    assert _row_to_candidate(row(shortName="Foo Acquisition Corp"), TODAY) is None

def test_missing_field_dropped():
    assert _row_to_candidate(row(marketCap=None), TODAY) is None
    r = row(); del r["fiftyTwoWeekHigh"]
    assert _row_to_candidate(r, TODAY) is None

def test_exchange_mapping():
    assert _row_to_candidate(row(exchange="NYQ"), TODAY).exchange == "NYSE"
    assert _row_to_candidate(row(exchange="ASE"), TODAY).exchange == "AMEX"
    assert _row_to_candidate(row(exchange="NMS"), TODAY).exchange == "NASDAQ"

def test_otc_and_unknown_exchanges_dropped():
    # pink sheets / OTC markets are not "US stocks at 52wk highs" for our
    # audience, and chart-img can't resolve them without an exchange prefix
    for code in ("PNK", "OQX", "OID", "???", None):
        assert _row_to_candidate(row(exchange=code), TODAY) is None
