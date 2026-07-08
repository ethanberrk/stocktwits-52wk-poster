import io
import json
import urllib.error
from datetime import date
import pytest
from src.source.base import Candidate
from src.publish.base import compose_post_text, PostResult
from src.publish.dryrun import DryRunPublisher
from src.publish.record import write_post_artifacts
from src.publish.stocktwits_pub import StocktwitsPublisher, PublishError

CAND = Candidate("AAPL", "Apple Inc.", "NASDAQ", 251.37, 1.84,
                 3.91e12, 252.0, "EQUITY")

def test_compose_is_cashtag_plus_fixed_phrase():
    # Deliberately no price/%chg/mcap: they'd be stale by read time.
    assert compose_post_text(CAND) == "$AAPL printed a new 52-week high today"

def test_compose_uses_stocktwits_cashtag_format_for_share_classes():
    # Yahoo says BRK-B; the Stocktwits cashtag is $BRK.B — a $BRK-B post
    # would never land in the ticker's stream
    c = Candidate("BRK-B", "Berkshire Hathaway", "NYSE", 500.0, 1.0,
                  1.1e12, 501.0, "EQUITY")
    assert compose_post_text(c) == "$BRK.B printed a new 52-week high today"

def test_dryrun_writes_png_and_txt(tmp_path):
    pub = DryRunPublisher(tmp_path, date(2026, 7, 1))
    res = pub.post(CAND, "$AAPL hello", b"\x89PNGfake")
    assert res == PostResult(post_id=None, dry_run=True)
    day = tmp_path / "2026-07-01"
    assert (day / "AAPL.png").read_bytes() == b"\x89PNGfake"
    assert (day / "AAPL.txt").read_text(encoding="utf-8") == "$AAPL hello"

def test_write_post_artifacts_creates_png_and_txt(tmp_path):
    write_post_artifacts(tmp_path, date(2026, 7, 8), "AAPL",
                         "$AAPL printed a new 52-week high today", b"\x89PNGdata")
    day = tmp_path / "2026-07-08"
    assert (day / "AAPL.png").read_bytes() == b"\x89PNGdata"
    assert (day / "AAPL.txt").read_text(encoding="utf-8") == \
        "$AAPL printed a new 52-week high today"


class _FakeResp:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

def _pub(tmp_path, urlopen):
    return StocktwitsPublisher("TOKEN123", tmp_path, date(2026, 7, 8),
                               user_agent="ua/1.0",
                               url="https://st.example/create.json",
                               urlopen=urlopen)

def test_stocktwits_post_sends_multipart_and_returns_id(tmp_path):
    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        captured["data"] = req.data
        return _FakeResp(json.dumps(
            {"response": {"status": 200}, "message": {"id": 98765}}).encode())
    res = _pub(tmp_path, fake_urlopen).post(
        CAND, "$AAPL printed a new 52-week high today", b"\x89PNGdata")
    assert res == PostResult(post_id="98765", dry_run=False)
    body = captured["data"]
    assert b'name="access_token"' in body and b"TOKEN123" in body
    assert b'name="body"' in body and b"printed a new 52-week high" in body
    assert b'name="chart"; filename=' in body and b"\x89PNGdata" in body
    ct = captured["headers"]["content-type"]
    assert ct.startswith("multipart/form-data; boundary=")
    assert captured["headers"]["user-agent"] == "ua/1.0"

def test_stocktwits_post_writes_output_artifacts_on_success(tmp_path):
    def fake_urlopen(req, timeout=None):
        return _FakeResp(json.dumps(
            {"response": {"status": 200}, "message": {"id": 1}}).encode())
    _pub(tmp_path, fake_urlopen).post(
        CAND, "$AAPL printed a new 52-week high today", b"\x89PNGdata")
    day = tmp_path / "2026-07-08"
    assert (day / "AAPL.png").read_bytes() == b"\x89PNGdata"
    assert (day / "AAPL.txt").read_text(encoding="utf-8").startswith("$AAPL")

def test_stocktwits_post_raises_on_http_error(tmp_path):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            "https://st.example/create.json", 403, "Forbidden", {},
            io.BytesIO(b"blocked by cloudflare"))
    with pytest.raises(PublishError):
        _pub(tmp_path, fake_urlopen).post(CAND, "text", b"PNG")
    # a failed post writes NO artifact (ticker stays pending -> audit WARN, no orphan)
    assert not (tmp_path / "2026-07-08").exists()

def test_stocktwits_post_raises_on_error_status_in_body(tmp_path):
    def fake_urlopen(req, timeout=None):
        return _FakeResp(json.dumps(
            {"response": {"status": 400}, "errors": [{"message": "bad"}]}).encode())
    with pytest.raises(PublishError):
        _pub(tmp_path, fake_urlopen).post(CAND, "text", b"PNG")

def test_stocktwits_publisher_uses_urllib_not_requests():
    import inspect
    import src.publish.stocktwits_pub as m
    assert "import requests" not in inspect.getsource(m)

def test_stocktwits_post_raises_on_unparseable_body(tmp_path):
    def fake_urlopen(req, timeout=None):
        return _FakeResp(b"<html>not json</html>")
    with pytest.raises(PublishError):
        _pub(tmp_path, fake_urlopen).post(CAND, "text", b"PNG")
    assert not (tmp_path / "2026-07-08").exists()   # no orphan artifact on failure

def test_stocktwits_post_raises_on_missing_message_id(tmp_path):
    def fake_urlopen(req, timeout=None):
        return _FakeResp(json.dumps({"response": {"status": 200}}).encode())
    with pytest.raises(PublishError):
        _pub(tmp_path, fake_urlopen).post(CAND, "text", b"PNG")
    assert not (tmp_path / "2026-07-08").exists()
