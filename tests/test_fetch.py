import io
import json
import urllib.error

from src.fetch import get_json


class _FakeOpener:
    """Stands in for urllib's opener: returns queued responses/exceptions."""
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def open(self, req, timeout=None):
        self.calls += 1
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return io.BytesIO(json.dumps(r).encode())


def test_get_json_returns_parsed_body():
    opener = _FakeOpener([{"data": {"p": 42.0}}])
    assert get_json("https://x.test/q", opener=opener) == {"data": {"p": 42.0}}


def test_get_json_retries_on_429_then_succeeds():
    err = urllib.error.HTTPError("u", 429, "too many", {}, None)
    opener = _FakeOpener([err, {"ok": 1}])
    assert get_json("https://x.test/q", opener=opener) == {"ok": 1}
    assert opener.calls == 2


def test_get_json_returns_none_on_404():
    err = urllib.error.HTTPError("u", 404, "nope", {}, None)
    opener = _FakeOpener([err])
    assert get_json("https://x.test/q", opener=opener) is None


def test_get_json_returns_none_when_all_tries_fail():
    opener = _FakeOpener([ConnectionError("x")] * 4)
    assert get_json("https://x.test/q", opener=opener, tries=4) is None
    assert opener.calls == 4
