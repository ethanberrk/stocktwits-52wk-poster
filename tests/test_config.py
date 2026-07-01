# tests/test_config.py
import re
import config

def test_caps_and_floors():
    assert config.MIN_MARKET_CAP == 1_000_000_000
    assert config.MAX_PER_TICK == 2
    assert config.MAX_PER_DAY == 20
    assert config.MAX_PLAUSIBLE_HIGHS == 500
    assert config.MARKET_TZ == "America/New_York"
    assert config.MARKET_OPEN == (9, 30)
    assert config.MARKET_CLOSE == (16, 0)

def test_name_exclusion_regex():
    bad = ["SPDR S&P 500 ETF", "Global Fund", "Acme Pfd Series A",
           "Foo Acquisition Corp", "Bar Units", "Baz Warrants"]
    good = ["Apple Inc.", "Union Pacific", "Fundamental Interactions Inc"]
    for name in bad:
        assert config.NAME_EXCLUDE_RE.search(name), name
    for name in good:
        assert not config.NAME_EXCLUDE_RE.search(name), name
