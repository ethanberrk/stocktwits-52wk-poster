# tests/test_config.py
import re
import importlib
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

def test_caps_are_env_overridable(monkeypatch):
    monkeypatch.setenv("MAX_PER_TICK", "1")
    monkeypatch.setenv("MAX_PER_DAY", "3")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.MAX_PER_TICK == 1
        assert reloaded.MAX_PER_DAY == 3
    finally:
        monkeypatch.delenv("MAX_PER_TICK", raising=False)
        monkeypatch.delenv("MAX_PER_DAY", raising=False)
        importlib.reload(config)  # restore defaults for other tests

def test_stocktwits_constants_present():
    assert config.STOCKTWITS_CREATE_URL == \
        "https://api.stocktwits.com/api/2/messages/create.json"
    assert config.STOCKTWITS_USER_AGENT == "stocktwits-52wk-poster/1.0"

def test_chart_source_config():
    # keyless stockanalysis endpoints drive the self-rendered charts
    assert "{ticker}" in config.SA_QUOTE_URL
    assert "{ticker}" in config.SA_HISTORY_URL
    assert "range=1Y" in config.SA_HISTORY_URL
    assert "period=Daily" in config.SA_HISTORY_URL
    assert config.MIN_HISTORY_DAYS == 330
    assert (config.CHART_WIDTH, config.CHART_HEIGHT) == (800, 450)
    # chart-img is gone entirely
    assert not hasattr(config, "CHART_IMG_URL")
