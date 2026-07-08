from datetime import date
from pathlib import Path

from src.publish.base import Publisher, PostResult
from src.publish.record import write_post_artifacts
from src.source.base import Candidate


class DryRunPublisher(Publisher):
    """Phase 1 stand-in: writes what *would* be posted to output/YYYY-MM-DD/."""

    def __init__(self, out_dir: Path, today: date):
        self.out_dir = Path(out_dir)
        self.today = today

    def post(self, candidate: Candidate, text: str, image_png: bytes) -> PostResult:
        write_post_artifacts(self.out_dir, self.today, candidate.ticker, text, image_png)
        return PostResult(post_id=None, dry_run=True)
