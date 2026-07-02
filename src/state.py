import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import config


def load_posted(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    return json.loads(Path(path).read_text())["posts"]


def append_posted(path: Path, ticker: str, day: date, post_id: str | None,
                  status: str = "posted") -> None:
    path = Path(path)
    posts = load_posted(path)
    posts.append({"ticker": ticker, "date": day.isoformat(),
                  "post_id": post_id, "status": status})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"posts": posts}, indent=2) + "\n")


def mark_posted(path: Path, ticker: str, day: date, post_id: str | None) -> None:
    """Confirm a write-ahead 'pending' entry after the post succeeded."""
    path = Path(path)
    posts = load_posted(path)
    for e in posts:
        if (e["ticker"] == ticker and e["date"] == day.isoformat()
                and e.get("status") == "pending"):
            e["status"] = "posted"
            e["post_id"] = post_id
            break
    path.write_text(json.dumps({"posts": posts}, indent=2) + "\n")


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:  # Sat=5, Sun=6; holidays deferred (see spec backlog)
        d -= timedelta(days=1)
    return d


def is_blocked(ticker: str, posted: list[dict], today: date) -> bool:
    dates = {date.fromisoformat(e["date"]) for e in posted if e["ticker"] == ticker}
    return today in dates or previous_trading_day(today) in dates


def daily_count(posted: list[dict], today: date) -> int:
    return sum(1 for e in posted if e["date"] == today.isoformat())


def is_market_hours(now_utc: datetime) -> bool:
    et = now_utc.astimezone(ZoneInfo(config.MARKET_TZ))
    if et.weekday() >= 5:
        return False
    return time(*config.MARKET_OPEN) <= et.time() < time(*config.MARKET_CLOSE)
