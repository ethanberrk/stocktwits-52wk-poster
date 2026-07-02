from datetime import date
from pathlib import Path

from src.publish.base import Publisher, PostResult
from src.source.base import Candidate

class DryRunPublisher(Publisher):
    """Phase 1 stand-in: writes what *would* be posted to output/YYYY-MM-DD/."""

    def __init__(self, out_dir: Path, today: date):
        self.day_dir = Path(out_dir) / today.isoformat()

    def post(self, candidate: Candidate, text: str, image_png: bytes) -> PostResult:
        self.day_dir.mkdir(parents=True, exist_ok=True)
        (self.day_dir / f"{candidate.ticker}.png").write_bytes(image_png)
        (self.day_dir / f"{candidate.ticker}.txt").write_text(text, encoding="utf-8")
        return PostResult(post_id=None, dry_run=True)
