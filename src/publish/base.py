from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.source.base import Candidate

@dataclass(frozen=True)
class PostResult:
    post_id: str | None
    dry_run: bool

class Publisher(ABC):
    @abstractmethod
    def post(self, candidate: Candidate, text: str, image_png: bytes) -> PostResult: ...

def _fmt_cap(mcap: float) -> str:
    if mcap >= 1e12:
        return f"${mcap / 1e12:.1f}T"
    return f"${mcap / 1e9:.1f}B"

def compose_post_text(c: Candidate) -> str:
    return (f"${c.ticker} printed a new 52-week high today. "
            f"{c.name} · ${c.price:,.2f} ({c.pct_change_today:+.1f}%) · "
            f"{_fmt_cap(c.market_cap)} market cap")
