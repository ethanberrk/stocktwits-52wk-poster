import pytest
import requests
import config
from src import chart
from src.source.base import Candidate

CAND = Candidate("AAPL", "Apple Inc.", "NASDAQ", 250.0, 1.8, 3.9e12, 252.0, "EQUITY")

def test_request_args():
    url, params, headers = chart._request_args(CAND, "k3y")
    assert url == config.CHART_IMG_URL
    assert params["symbol"] == "NASDAQ:AAPL"
    assert params["interval"] == "1D"
    assert params["range"] == "1Y"
    assert headers == {"x-api-key": "k3y"}

def test_request_args_no_exchange_falls_back_to_bare_ticker():
    c = Candidate("FOO", "Foo Inc", "", 10.0, 1.0, 2e9, 11.0, "EQUITY")
    _, params, _ = chart._request_args(c, "k")
    assert params["symbol"] == "FOO"

class FakeResp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content

def test_fetch_returns_bytes_on_200(monkeypatch):
    monkeypatch.setattr(requests, "get",
                        lambda url, params, headers, timeout: FakeResp(200, b"PNG!"))
    assert chart.fetch_chart_png(CAND, "k") == b"PNG!"

def test_fetch_raises_chart_error_on_429(monkeypatch):
    monkeypatch.setattr(requests, "get",
                        lambda url, params, headers, timeout: FakeResp(429))
    with pytest.raises(chart.ChartError):
        chart.fetch_chart_png(CAND, "k")

def test_fetch_raises_chart_error_on_network_failure(monkeypatch):
    def boom(url, params, headers, timeout):
        raise requests.ConnectionError("nope")
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(chart.ChartError):
        chart.fetch_chart_png(CAND, "k")
