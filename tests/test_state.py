from datetime import date, datetime, timezone
from src import state


def entry(ticker, d):
    return {"ticker": ticker, "date": d.isoformat(), "post_id": None}


def test_previous_trading_day_skips_weekend():
    assert state.previous_trading_day(date(2026, 7, 1)) == date(2026, 6, 30)  # Wed -> Tue
    assert state.previous_trading_day(date(2026, 6, 29)) == date(2026, 6, 26)  # Mon -> Fri


def test_cooldown_monday_post_blocks_tuesday_not_wednesday():
    posted = [entry("AAPL", date(2026, 6, 29))]                # posted Monday
    assert state.is_blocked("AAPL", posted, date(2026, 6, 29))  # same day
    assert state.is_blocked("AAPL", posted, date(2026, 6, 30))  # Tuesday
    assert not state.is_blocked("AAPL", posted, date(2026, 7, 1))  # Wednesday: eligible


def test_cooldown_friday_post_blocks_monday_not_tuesday():
    posted = [entry("NVDA", date(2026, 6, 26))]                # posted Friday
    assert state.is_blocked("NVDA", posted, date(2026, 6, 29))  # Monday blocked
    assert not state.is_blocked("NVDA", posted, date(2026, 6, 30))  # Tuesday eligible


def test_daily_count_counts_only_today():
    posted = [entry("A", date(2026, 7, 1)), entry("B", date(2026, 7, 1)),
              entry("C", date(2026, 6, 30))]
    assert state.daily_count(posted, date(2026, 7, 1)) == 2


def test_pending_writeahead_blocks_and_marks_posted(tmp_path):
    # at-most-once: intent is recorded (pending) before an irreversible
    # post, blocks like a real post, and is confirmed afterwards
    p = tmp_path / "posted.json"
    state.append_posted(p, "V", date(2026, 7, 2), None, status="pending")
    got = state.load_posted(p)
    assert got[0]["status"] == "pending" and got[0]["post_id"] is None
    assert state.is_blocked("V", got, date(2026, 7, 2))
    assert state.daily_count(got, date(2026, 7, 2)) == 1

    state.mark_posted(p, "V", date(2026, 7, 2), "98765")
    got = state.load_posted(p)
    assert got[0]["status"] == "posted" and got[0]["post_id"] == "98765"


def test_legacy_entries_without_status_still_block():
    posted = [{"ticker": "V", "date": "2026-07-01", "post_id": None}]
    assert state.is_blocked("V", posted, date(2026, 7, 2))


def test_posted_log_roundtrip(tmp_path):
    p = tmp_path / "state" / "posted.json"
    assert state.load_posted(p) == []
    state.append_posted(p, "AAPL", date(2026, 7, 1), None)
    state.append_posted(p, "MSFT", date(2026, 7, 1), "12345")
    got = state.load_posted(p)
    assert [e["ticker"] for e in got] == ["AAPL", "MSFT"]
    assert got[1]["post_id"] == "12345"


def test_market_hours_edt():
    # 2026-07-01 is EDT (UTC-4): 14:00 UTC = 10:00 ET -> open
    assert state.is_market_hours(datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc))
    # 21:00 UTC = 17:00 ET -> closed
    assert not state.is_market_hours(datetime(2026, 7, 1, 21, 0, tzinfo=timezone.utc))


def test_market_hours_est_and_weekend():
    # 2026-01-14 is EST (UTC-5): 14:00 UTC = 09:00 ET -> before open
    assert not state.is_market_hours(datetime(2026, 1, 14, 14, 0, tzinfo=timezone.utc))
    # 15:00 UTC = 10:00 ET -> open
    assert state.is_market_hours(datetime(2026, 1, 14, 15, 0, tzinfo=timezone.utc))
    # Saturday
    assert not state.is_market_hours(datetime(2026, 7, 4, 15, 0, tzinfo=timezone.utc))
