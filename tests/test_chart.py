import pytest
import requests
import config
from src import chart
from src.source.base import Candidate

CAND = Candidate("AAPL", "Apple Inc.", "NASDAQ", 250.0, 1.8, 3.9e12, 252.0, "EQUITY")

def test_request_args():
    url, body, headers = chart._request_args(CAND, "k3y")
    assert url == config.CHART_IMG_URL
    assert body["symbol"] == "NASDAQ:AAPL"
    assert body["interval"] == "1D"
    assert body["range"] == "1Y"
    assert body["session"] == "regular"   # exclude pre/post-market hours
    assert headers == {"x-api-key": "k3y"}

def test_targets_v2_endpoint():
    # v2 is the only version with session control; on v1 a chart captured in
    # the opening minute could freeze an extended-hours "Pre" price line.
    assert "/v2/" in config.CHART_IMG_URL

def test_request_args_no_exchange_falls_back_to_bare_ticker():
    c = Candidate("FOO", "Foo Inc", "", 10.0, 1.0, 2e9, 11.0, "EQUITY")
    _, body, _ = chart._request_args(c, "k")
    assert body["symbol"] == "FOO"

class FakeResp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content

def test_fetch_returns_bytes_on_200(monkeypatch):
    monkeypatch.setattr(requests, "post",
                        lambda url, json, headers, timeout: FakeResp(200, b"PNG!"))
    assert chart.fetch_chart_png(CAND, "k") == b"PNG!"

def test_fetch_posts_json_body_to_v2(monkeypatch):
    seen = {}
    def capture(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return FakeResp(200, b"PNG!")
    monkeypatch.setattr(requests, "post", capture)
    chart.fetch_chart_png(CAND, "k")
    assert seen["url"] == config.CHART_IMG_URL
    assert seen["json"]["session"] == "regular"
    assert seen["headers"] == {"x-api-key": "k"}

def test_fetch_raises_chart_error_on_429(monkeypatch):
    monkeypatch.setattr(requests, "post",
                        lambda url, json, headers, timeout: FakeResp(429))
    with pytest.raises(chart.ChartError):
        chart.fetch_chart_png(CAND, "k")

def test_fetch_raises_chart_error_on_network_failure(monkeypatch):
    def boom(url, json, headers, timeout):
        raise requests.ConnectionError("nope")
    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(chart.ChartError):
        chart.fetch_chart_png(CAND, "k")
