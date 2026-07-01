from datetime import date
import pytest
import config
from src import select
from src.source.base import Candidate

TODAY = date(2026, 7, 1)  # Wednesday

def cand(ticker, mcap):
    return Candidate(ticker, f"{ticker} Inc", "NYSE", 100.0, 2.0,
                     mcap, 101.0, "EQUITY")

def posted_entry(ticker, d=TODAY):
    return {"ticker": ticker, "date": d.isoformat(), "post_id": None}

def test_validate_rejects_implausible_count():
    cands = [cand(f"T{i}", 2e9) for i in range(config.MAX_PLAUSIBLE_HIGHS + 1)]
    with pytest.raises(select.ValidationError):
        select.validate(cands)
    select.validate(cands[:10])  # plausible: no raise

def test_pick_filters_mcap_and_ranks_desc():
    cands = [cand("SMALL", 5e8), cand("MID", 5e9), cand("BIG", 5e11)]
    got = select.pick(cands, [], TODAY)
    assert [c.ticker for c in got] == ["BIG", "MID"]  # SMALL under $1B; 2-per-tick cap

def test_pick_respects_cooldown():
    cands = [cand("A", 3e9), cand("B", 2e9)]
    posted = [posted_entry("A", date(2026, 6, 30))]  # posted Tuesday -> blocked Wed
    assert [c.ticker for c in select.pick(cands, posted, TODAY)] == ["B"]

def test_pick_respects_daily_cap():
    cands = [cand("A", 3e9), cand("B", 2e9)]
    posted = [posted_entry(f"T{i}") for i in range(config.MAX_PER_DAY - 1)]
    got = select.pick(cands, posted, TODAY)   # only 1 slot left today
    assert [c.ticker for c in got] == ["A"]
    posted.append(posted_entry("T-last"))     # cap reached
    assert select.pick(cands, posted, TODAY) == []
