"""Unit tests for the Xignite 52-week-high source: universe parsing, the
day-cumulative test, candidate hygiene, and the fetch flow."""
from datetime import date

import pytest

import config
from src import xignite
from src.source import xignite_source as xs
from src.source.base import SourceError

NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
AAAP|Pacer Barings CLO Market Flex ETF|G|N|N|100|Y|N
BFRGW|Bullfrog AI Holdings, Inc. - Warrants|S|N|N|100|N|N
BRKHU|Burtech Acquisition Corp II - Units|S|N|N|100|N|N
ZTST|Test Issue Inc|Q|Y|N|100|N|N
File Creation Time: 0903202614:01|||||||
"""
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
A|Agilent Technologies, Inc. Common Stock|N|A|N|100|N|A
BRK.B|Berkshire Hathaway Inc. New Common Stock|N|BRK B|N|100|N|BRK.B
BAC$B|Bank of America Depositary Shares Preferred Series GG|N|BACpB|N|100|N|BAC-B
AAC.U|Ares Acquisition Corporation III Units|N|AAC.U|N|100|N|AAC=
SPY|SPDR S&P 500|P|SPY|Y|100|N|SPY
BTG|B2Gold Corp Common Shares|A|BTG|N|100|N|BTG
UAMY|United States Antimony Corp|A|UAMY|N|100|N|UAMY
"""


def _fetch(url):
    return NASDAQ if "nasdaqlisted" in url else OTHER


def test_canonical_ticker_shapes():
    assert xs.canonical_ticker("AAPL") == "AAPL"
    assert xs.canonical_ticker("BRK.B") == "BRK-B"
    assert xs.canonical_ticker("BAC$B") is None          # preferred
    assert xs.canonical_ticker("AAC.U") is None          # unit
    assert xs.canonical_ticker("ACHR.W") is None         # warrant
    assert xs.canonical_ticker("BFRGW") is None          # Nasdaq warrant shape
    assert xs.canonical_ticker("") is None


def test_listed_universe_filters_and_dash_form(monkeypatch):
    monkeypatch.setattr(config, "MIN_UNIVERSE_SIZE", 1)
    pairs = xs.listed_universe(_fetch)
    assert [t for t, _ in pairs] == ["AAPL", "A", "BRK-B", "BTG", "UAMY"]


def test_listed_universe_floor_trips_on_tiny_list():
    with pytest.raises(SourceError, match="look broken"):
        xs.listed_universe(_fetch)


def test_listed_universe_empty_files_fail():
    with pytest.raises(SourceError):
        xs.listed_universe(lambda url: "")


def _q(**kw):
    base = {"Identifier": "DELL", "Outcome": "Success", "Date": "9/3/2026",
            "Open": 500, "High": 530.78, "Low": 499, "Last": 528.0,
            "High52Weeks": 530.78, "PercentChangeFromPreviousClose": 2.1,
            "Security": {"Name": "Dell Technologies Inc", "Market": "NYSE"}}
    base.update(kw)
    return base


TODAY = date(2026, 9, 3)


def test_is_new_high_day_cumulative_and_fresh():
    assert xs.is_new_high(_q(), TODAY)
    assert xs.is_new_high(_q(High=530.78, High52Weeks=530.7800001), TODAY)   # float slack
    assert not xs.is_new_high(_q(High=530.0), TODAY)                        # below
    assert not xs.is_new_high(_q(Date="9/2/2026"), TODAY)                   # stale / holiday
    assert not xs.is_new_high(_q(High=0, High52Weeks=0), TODAY)             # no data


def test_build_candidate_maps_fields():
    c = xs.build_candidate("DELL", "Dell (SEC name)", _q(), 3.6e11)
    assert (c.ticker, c.exchange, c.price, c.market_cap, c.week52_high) == \
        ("DELL", "NYSE", 528.0, 3.6e11, 530.78)
    assert c.pct_change_today == 2.1 and c.security_type == "EQUITY"
    assert c.name == "Dell Technologies Inc"


def test_build_candidate_hygiene():
    assert xs.build_candidate("X", "n", _q(Security={"Name": "X", "Market": "OTC"}), 5e9) is None
    assert xs.build_candidate("X", "n", _q(Security={"Name": "X Warrants", "Market": "NYSE"}), 5e9) is None
    assert xs.build_candidate("X", "n", _q(), None) is None                       # no mcap
    assert xs.build_candidate("X", "n", _q(), config.MIN_MARKET_CAP - 1) is None  # below floor
    assert xs.build_candidate("X", "n", _q(Last=0), 5e9) is None


def test_fetch_candidates_only_asks_mcap_for_hits(monkeypatch):
    universe = [("DELL", "Dell"), ("AAPL", "Apple"), ("SMALL", "Small Co")]
    quotes = {"DELL": _q(), "AAPL": _q(Identifier="AAPL", High=300, High52Weeks=344),
              "SMALL": _q(Identifier="SMALL")}
    asked = []

    def caps(tickers):
        asked.extend(tickers)
        return {"DELL": 3.6e11, "SMALL": 5e8}
    monkeypatch.setattr(xignite, "quotes", lambda tks: quotes)
    monkeypatch.setattr(xignite, "market_caps", caps)
    monkeypatch.setattr(xs, "datetime", _FakeDT)
    out = xs.XigniteSource(universe=lambda: universe).fetch_candidates()
    assert asked == ["DELL", "SMALL"]           # AAPL not at a high -> never priced
    assert [c.ticker for c in out] == ["DELL"]  # SMALL under the $1B floor


def test_fetch_candidates_zero_quotes_is_broken_feed(monkeypatch):
    monkeypatch.setattr(xignite, "quotes", lambda tks: {})
    with pytest.raises(SourceError, match="zero quotes"):
        xs.XigniteSource(universe=lambda: [("AAPL", "Apple")]).fetch_candidates()


class _FakeDT:
    @staticmethod
    def now(tz=None):
        from datetime import datetime
        return datetime(2026, 9, 3, 14, 0, tzinfo=tz)
