from datetime import date
from src.source.base import Candidate
from src.publish.base import compose_post_text, PostResult
from src.publish.dryrun import DryRunPublisher

CAND = Candidate("AAPL", "Apple Inc.", "NASDAQ", 251.37, 1.84,
                 3.91e12, 252.0, "EQUITY")

def test_compose_starts_with_cashtag_and_has_facts():
    text = compose_post_text(CAND)
    assert text.startswith("$AAPL ")
    assert "52-week high" in text
    assert "$251.37" in text
    assert "+1.8%" in text
    assert "$3.9T" in text

def test_compose_billions_cap():
    c = Candidate("ZS", "Zscaler", "NASDAQ", 300.0, -0.5, 45.2e9, 305.0, "EQUITY")
    assert "$45.2B" in compose_post_text(c)
    assert "-0.5%" in compose_post_text(c)

def test_dryrun_writes_png_and_txt(tmp_path):
    pub = DryRunPublisher(tmp_path, date(2026, 7, 1))
    res = pub.post(CAND, "$AAPL hello", b"\x89PNGfake")
    assert res == PostResult(post_id=None, dry_run=True)
    day = tmp_path / "2026-07-01"
    assert (day / "AAPL.png").read_bytes() == b"\x89PNGfake"
    assert (day / "AAPL.txt").read_text(encoding="utf-8") == "$AAPL hello"
