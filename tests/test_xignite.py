"""Unit tests for the Xignite client: symbology, batching, broken-feed
detection, market-cap units, history parsing, today's candle."""
from datetime import date

import pytest

import config
from src import xignite
from src.source.base import SourceError


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setattr(config, "XIGNITE_TOKEN", "tok")


def _ok_quote(sym, **kw):
    return {"Identifier": sym, "Outcome": "Success", "Date": "9/3/2026", "Open": 10,
            "High": 11, "Low": 9, "Last": 10.5, "High52Weeks": 11, "Low52Weeks": 5,
            "Security": {"Name": f"{sym} Inc", "Market": "NYSE"}, **kw}


def test_xig_symbol_uses_dots_for_share_classes():
    assert xignite.xig_symbol("BRK-B") == "BRK.B"
    assert xignite.xig_symbol("AAPL") == "AAPL"


def test_parse_dates_both_formats():
    assert xignite.parse_xig_date("9/3/2026") == date(2026, 9, 3)
    assert xignite.parse_xig_date("2026-09-03") == date(2026, 9, 3)
    assert xignite.parse_xig_date(None) is None
    assert xignite.parse_xig_date("garbage") is None


def test_missing_token_is_a_source_error(monkeypatch):
    monkeypatch.setattr(config, "XIGNITE_TOKEN", "")
    with pytest.raises(SourceError, match="XIGNITE_TOKEN"):
        xignite.quotes(["AAPL"])


def test_quotes_batches_and_keys_by_dash_ticker(monkeypatch):
    monkeypatch.setattr(config, "XIGNITE_BATCH", 2)
    calls = []

    def fake_get(url, params):
        calls.append(params["Identifiers"])
        return [_ok_quote(s) for s in params["Identifiers"].split(",")]
    monkeypatch.setattr(xignite, "_get", fake_get)
    out = xignite.quotes(["AAPL", "BRK-B", "MSFT"])
    assert calls == ["AAPL,BRK.B", "MSFT"]
    assert set(out) == {"AAPL", "BRK-B", "MSFT"}
    assert out["BRK-B"]["Identifier"] == "BRK.B"


def test_quotes_drops_unmatched_symbols(monkeypatch):
    monkeypatch.setattr(xignite, "_get", lambda u, p: [
        _ok_quote("AAPL"),
        {"Identifier": "ZZZZ", "Outcome": "RequestError", "Message": "No match"}])
    assert set(xignite.quotes(["AAPL", "ZZZZ"])) == {"AAPL"}


def test_batch_with_zero_successes_fails_red(monkeypatch):
    monkeypatch.setattr(xignite, "_get", lambda u, p: [
        {"Outcome": "RegistrationError", "Message": "token expired"}])
    with pytest.raises(SourceError, match="token expired"):
        xignite.quotes(["AAPL"])


def test_empty_batch_response_fails_red(monkeypatch):
    monkeypatch.setattr(xignite, "_get", lambda u, p: None)
    with pytest.raises(SourceError):
        xignite.quotes(["AAPL"])


def test_market_caps_scale_by_unit(monkeypatch):
    def fake_get(url, params):
        assert params["FundamentalTypes"] == "MarketCapitalization"
        return [
            {"Outcome": "Success", "Company": {"Symbol": "AAPL"},
             "FundamentalsSets": [{"Fundamentals": [
                 {"Type": "MarketCapitalization", "Value": "4742531.232", "Unit": "Millions"}]}]},
            {"Outcome": "Success", "Company": {"Symbol": "BRK.B"},
             "FundamentalsSets": [{"Fundamentals": [
                 {"Type": "MarketCapitalization", "Value": "1.08", "Unit": "Billions"}]}]},
            {"Outcome": "Success", "Company": {"Symbol": "NOPE"}, "FundamentalsSets": []},
        ]
    monkeypatch.setattr(xignite, "_get", fake_get)
    caps = xignite.market_caps(["AAPL", "BRK-B", "NOPE"])
    assert caps["AAPL"] == pytest.approx(4.742531232e12)
    assert caps["BRK-B"] == pytest.approx(1.08e9)
    assert "NOPE" not in caps


def test_history_sorted_ascending_and_skips_empty_closes(monkeypatch):
    seen = {}

    def fake_get(url, params):
        seen.update(params)
        return {"Outcome": "Success", "HistoricalQuotes": [
            {"Date": "2026-09-02", "Open": 2, "High": 3, "Low": 1, "Close": 2.5},
            {"Date": "2026-09-01", "Open": 1, "High": 2, "Low": 0.5, "Close": 1.5},
            {"Date": "2026-08-31", "Open": 0, "High": 0, "Low": 0, "Close": 0},
        ]}
    monkeypatch.setattr(xignite, "_get", fake_get)
    hist = xignite.history("BRK-B", date(2026, 9, 3))
    assert [r[0] for r in hist] == ["2026-09-01", "2026-09-02"]
    assert hist[-1] == ["2026-09-02", 2.0, 3.0, 1.0, 2.5]
    assert seen["Identifier"] == "BRK.B"
    assert seen["EndDate"] == "9/3/2026"
    assert seen["AdjustmentMethod"] == "SplitOnly"


def test_history_failure_is_source_error(monkeypatch):
    monkeypatch.setattr(xignite, "_get", lambda u, p: {"Outcome": "RequestError", "Message": "nope"})
    with pytest.raises(SourceError, match="nope"):
        xignite.history("AAPL", date(2026, 9, 3))


def test_today_candle_requires_todays_date_and_prices():
    today = date(2026, 9, 3)
    assert xignite.today_candle(_ok_quote("AAPL"), today) == ["2026-09-03", 10.0, 11.0, 9.0, 10.5]
    assert xignite.today_candle(_ok_quote("AAPL", Date="9/2/2026"), today) is None
    assert xignite.today_candle(_ok_quote("AAPL", Open=0), today) is None
