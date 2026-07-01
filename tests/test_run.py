from datetime import datetime, timezone, date
import pytest
import run
from src.chart import ChartError
from src.source.base import Candidate, HighsSource
from src.publish.base import Publisher, PostResult
from src import state

NOW = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)  # Wed 10:00 ET, market open
TODAY = date(2026, 7, 1)

def cand(ticker, mcap=5e9):
    return Candidate(ticker, f"{ticker} Inc", "NYSE", 100.0, 2.0, mcap, 101.0, "EQUITY")

class FakeSource(HighsSource):
    def __init__(self, cands): self.cands = cands
    def fetch_candidates(self): return self.cands

class SpyPublisher(Publisher):
    def __init__(self): self.calls = []
    def post(self, candidate, text, image_png):
        self.calls.append((candidate.ticker, text, image_png))
        return PostResult(post_id=None, dry_run=True)

def test_tick_posts_top_candidates_and_records_state(tmp_path):
    sp = tmp_path / "posted.json"
    pub = SpyPublisher()
    got = run.tick(FakeSource([cand("BIG", 9e9), cand("MID", 5e9), cand("SM", 2e9)]),
                   pub, lambda c: b"PNG", sp, NOW)
    assert got == ["BIG", "MID"]                      # 2-per-tick cap, mcap order
    assert pub.calls[0][0] == "BIG"
    assert pub.calls[0][1].startswith("$BIG ")
    assert [e["ticker"] for e in state.load_posted(sp)] == ["BIG", "MID"]

def test_tick_outside_market_hours_is_noop(tmp_path):
    closed = datetime(2026, 7, 1, 22, 0, tzinfo=timezone.utc)  # 18:00 ET
    pub = SpyPublisher()
    got = run.tick(FakeSource([cand("BIG")]), pub, lambda c: b"PNG",
                   tmp_path / "p.json", closed)
    assert got == [] and pub.calls == []

def test_tick_force_overrides_hours(tmp_path):
    closed = datetime(2026, 7, 1, 22, 0, tzinfo=timezone.utc)
    got = run.tick(FakeSource([cand("BIG")]), SpyPublisher(), lambda c: b"PNG",
                   tmp_path / "p.json", closed, force=True)
    assert got == ["BIG"]

def test_chart_failure_skips_ticker_and_continues(tmp_path):
    def flaky(c):
        if c.ticker == "BIG":
            raise ChartError("boom")
        return b"PNG"
    pub = SpyPublisher()
    got = run.tick(FakeSource([cand("BIG", 9e9), cand("MID", 5e9)]),
                   pub, flaky, tmp_path / "p.json", NOW)
    assert got == ["MID"]                    # BIG skipped, stays unposted/eligible
    posted = state.load_posted(tmp_path / "p.json")
    assert [e["ticker"] for e in posted] == ["MID"]

def test_second_tick_same_day_respects_cooldown(tmp_path):
    sp = tmp_path / "posted.json"
    src = FakeSource([cand("BIG", 9e9), cand("MID", 5e9), cand("SM", 2e9)])
    run.tick(src, SpyPublisher(), lambda c: b"PNG", sp, NOW)
    got2 = run.tick(src, SpyPublisher(), lambda c: b"PNG", sp, NOW)
    assert got2 == ["SM"]                    # BIG/MID posted today -> blocked
