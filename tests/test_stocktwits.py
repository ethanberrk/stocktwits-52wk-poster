import urllib.error
import urllib.request

from src import stocktwits
from src.source.base import Candidate

def cand(ticker):
    return Candidate(ticker, "X Corp", "NYSE", 100.0, 1.0, 5e9, 101.0, "EQUITY")

def test_st_symbol_maps_yahoo_share_classes_to_stocktwits_dots():
    assert stocktwits.st_symbol("BRK-B") == "BRK.B"
    assert stocktwits.st_symbol("BF-B") == "BF.B"
    assert stocktwits.st_symbol("AAPL") == "AAPL"

class FakeResp:
    def __init__(self, status):
        self.status = status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False

def test_symbol_exists_true_on_200(monkeypatch):
    seen = {}
    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return FakeResp(200)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert stocktwits.symbol_exists(cand("BRK-B")) is True
    assert "BRK.B.json" in seen["url"]          # queried in Stocktwits format

def test_symbol_exists_false_on_definitive_404(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert stocktwits.symbol_exists(cand("ZZZQ")) is False

def test_symbol_exists_allows_on_indeterminate_403(monkeypatch):
    # datacenter-IP bot-walls must not silence all posting
    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", None, None)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert stocktwits.symbol_exists(cand("AAPL")) is True

def test_symbol_exists_allows_on_network_error(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert stocktwits.symbol_exists(cand("AAPL")) is True
