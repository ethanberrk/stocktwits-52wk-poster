from datetime import date
from pathlib import Path


def write_post_artifacts(out_dir: Path, today: date, ticker: str,
                         text: str, image_png: bytes) -> None:
    """Write the auditable record of a post: <out_dir>/<day>/<ticker>.{png,txt}.

    Shared by DryRunPublisher (Phase 1) and StocktwitsPublisher (Phase 2) so the
    nightly audit sees identical artifacts regardless of which one ran.
    """
    day_dir = Path(out_dir) / today.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / f"{ticker}.png").write_bytes(image_png)
    (day_dir / f"{ticker}.txt").write_text(text, encoding="utf-8")
