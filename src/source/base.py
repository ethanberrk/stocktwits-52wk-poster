from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class Candidate:
    ticker: str
    name: str
    exchange: str            # TradingView-style: "NASDAQ" | "NYSE" | "AMEX" | ""
    price: float
    pct_change_today: float
    market_cap: float
    week52_high: float
    security_type: str       # Yahoo quoteType, e.g. "EQUITY"

class SourceError(Exception):
    """The source itself looks broken (not merely 'no highs right now')."""

class HighsSource(ABC):
    @abstractmethod
    def fetch_candidates(self) -> list[Candidate]:
        """All US equities on today's 52-week-high list (day-cumulative)."""
