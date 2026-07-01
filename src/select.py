from datetime import date

import config
from src import state
from src.source.base import Candidate

class ValidationError(Exception):
    """Source output looks broken; abort the tick before posting anything."""

def validate(candidates: list[Candidate]) -> None:
    if len(candidates) > config.MAX_PLAUSIBLE_HIGHS:
        raise ValidationError(
            f"{len(candidates)} '52-week highs' is implausible "
            f"(gate: {config.MAX_PLAUSIBLE_HIGHS}); refusing to post")

def pick(candidates: list[Candidate], posted: list[dict], today: date) -> list[Candidate]:
    eligible = [c for c in candidates
                if c.market_cap >= config.MIN_MARKET_CAP
                and not state.is_blocked(c.ticker, posted, today)]
    eligible.sort(key=lambda c: c.market_cap, reverse=True)
    remaining_today = config.MAX_PER_DAY - state.daily_count(posted, today)
    n = max(0, min(config.MAX_PER_TICK, remaining_today))
    return eligible[:n]
