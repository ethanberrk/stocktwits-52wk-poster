from datetime import date
from src.source.base import Candidate
from src.publish.base import compose_post_text, PostResult
from src.publish.dryrun import DryRunPublisher

CAND = Candidate("AAPL", "Apple Inc.", "NASDAQ", 251.37, 1.84,
                 3.91e12, 252.0, "EQUITY")

def test_compose_is_cashtag_plus_fixed_phrase():
    # Deliberately no price/%chg/mcap: they'd be stale by read time.
    assert compose_post_text(CAND) == "$AAPL printed a new 52-week high today"

def test_dryrun_writes_png_and_txt(tmp_path):
    pub = DryRunPublisher(tmp_path, date(2026, 7, 1))
    res = pub.post(CAND, "$AAPL hello", b"\x89PNGfake")
    assert res == PostResult(post_id=None, dry_run=True)
    day = tmp_path / "2026-07-01"
    assert (day / "AAPL.png").read_bytes() == b"\x89PNGfake"
    assert (day / "AAPL.txt").read_text(encoding="utf-8") == "$AAPL hello"
