# Stocktwits 52-Week-High Poster — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GitHub-Actions cron that, every 30 minutes during US market hours, finds large-cap stocks on today's 52-week-high list and "posts" the best 1–2 (chart PNG + cashtag blurb) via a dry-run publisher, with state preventing consecutive-day reposts.

**Architecture:** One Python package, one tick per invocation. Stages behind interfaces: `HighsSource` (yfinance) → select (filters/cooldown/caps/mcap ranking) → chart (chart-img.com client) → `Publisher` (dry-run writer in Phase 1). State is a single committed JSON posted-log; the daily count is derived from it (the spec listed a separate `daily_count.json` — deriving it from the log is strictly simpler with identical behavior, so this plan uses one file).

**Tech Stack:** Python 3.12, `yfinance`, `requests`, `pytest`, stdlib `zoneinfo`/`dataclasses`. GitHub Actions for cron + CI.

**Spec:** `docs/superpowers/specs/2026-07-01-stocktwits-52wk-poster-design.md` (approved). One contract extension vs the spec: `Candidate` gains an `exchange` field, required to form the `EXCHANGE:TICKER` symbol chart-img expects.

## Global Constraints

- Python 3.12; runtime deps only `yfinance` and `requests`; `pytest` is dev-only.
- Caps: max **2 posts per tick**, max **20 posts per day** (config constants, never hardcoded elsewhere).
- Filters: market cap **≥ $1,000,000,000**; common stock only (Yahoo `quoteType == "EQUITY"` plus name-regex exclusion of ETF/Fund/Pfd/Preferred/Notes/Units/Warrants/Bond/Rights/Acquisition Corp).
- Eligibility is **day-cumulative**: on today's 52-week-high list = today's intraday high ≥ 52-week high, even if the stock has pulled back since.
- Cooldown: skip a ticker posted **today or the previous trading day** (weekends are not gap days; holidays deferred per spec).
- All market-time logic in `America/New_York` via `zoneinfo`; cron fires in UTC and code gates itself.
- Phase 1 has **no Stocktwits client** — the only publisher is dry-run to `output/YYYY-MM-DD/`.
- Contract tests (live yfinance / chart-img) are excluded from CI via pytest marker `contract`.
- Every commit message uses conventional prefixes (`feat:`, `test:`, `chore:`, `ci:`).

---

### Task 1: Project scaffold + config

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `config.py`, `src/__init__.py`, `src/source/__init__.py`, `src/publish/__init__.py`, `tests/__init__.py`, `state/.gitkeep`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `config` module importable as `import config` from repo root, with constants `MIN_MARKET_CAP: float`, `MAX_PER_TICK: int`, `MAX_PER_DAY: int`, `MAX_PLAUSIBLE_HIGHS: int`, `MARKET_TZ: str`, `MARKET_OPEN: tuple[int,int]`, `MARKET_CLOSE: tuple[int,int]`, `CHART_IMG_URL: str`, `NAME_EXCLUDE_RE: re.Pattern`. Pytest configured so `src.*` imports resolve and `-m "not contract"` is the default.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import re
import config

def test_caps_and_floors():
    assert config.MIN_MARKET_CAP == 1_000_000_000
    assert config.MAX_PER_TICK == 2
    assert config.MAX_PER_DAY == 20
    assert config.MAX_PLAUSIBLE_HIGHS == 500
    assert config.MARKET_TZ == "America/New_York"
    assert config.MARKET_OPEN == (9, 30)
    assert config.MARKET_CLOSE == (16, 0)

def test_name_exclusion_regex():
    bad = ["SPDR S&P 500 ETF", "Global Fund", "Acme Pfd Series A",
           "Foo Acquisition Corp", "Bar Units", "Baz Warrants"]
    good = ["Apple Inc.", "Union Pacific", "Fundamental Interactions Inc"]
    for name in bad:
        assert config.NAME_EXCLUDE_RE.search(name), name
    for name in good:
        assert not config.NAME_EXCLUDE_RE.search(name), name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ethanberk/stocktwits-52wk-poster && python3 -m pytest tests/test_config.py -v`
Expected: FAIL / error with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Write scaffold + minimal implementation**

```toml
# pyproject.toml
[project]
name = "stocktwits-52wk-poster"
version = "0.1.0"
requires-python = ">=3.12"

[tool.pytest.ini_options]
pythonpath = ["."]
addopts = "-m 'not contract'"
markers = ["contract: live external-API tests, run manually only"]
```

```
# requirements.txt
yfinance>=0.2.50
requests>=2.31
```

```
# requirements-dev.txt
-r requirements.txt
pytest>=8.0
```

```
# .gitignore
__pycache__/
*.pyc
.venv/
.pytest_cache/
```

```python
# config.py
"""All knobs in one place. Nothing else defines numbers or thresholds."""
import re

MIN_MARKET_CAP = 1_000_000_000          # USD floor
MAX_PER_TICK = 2                        # posts per 30-min tick
MAX_PER_DAY = 20                        # posts per trading day
MAX_PLAUSIBLE_HIGHS = 500               # validation gate: more = broken source

MARKET_TZ = "America/New_York"
MARKET_OPEN = (9, 30)                   # ET
MARKET_CLOSE = (16, 0)                  # ET

CHART_IMG_URL = "https://api.chart-img.com/v1/tradingview/advanced-chart"

# Drop non-common-equity by name (same rule the WSJ prototype proved out)
NAME_EXCLUDE_RE = re.compile(
    r"\b(ETF|Fund|Pfd|Preferred|Notes?|Units?|Warrants?|Wt|Bond|Rt|Rights)\b"
    r"|Acquisition Corp",
    re.I,
)
```

Create empty `src/__init__.py`, `src/source/__init__.py`, `src/publish/__init__.py`, `tests/__init__.py`, and `state/.gitkeep`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "chore: scaffold project, pytest config, and config knobs"
```

---

### Task 2: Candidate model + yfinance row parsing

**Files:**
- Create: `src/source/base.py`, `src/source/yfinance_source.py`
- Test: `tests/test_source_parse.py`

**Interfaces:**
- Consumes: `config.NAME_EXCLUDE_RE`
- Produces:
  - `src.source.base.Candidate` — frozen dataclass: `ticker: str, name: str, exchange: str, price: float, pct_change_today: float, market_cap: float, week52_high: float, security_type: str`
  - `src.source.base.HighsSource` — ABC with `fetch_candidates(self) -> list[Candidate]`
  - `src.source.base.SourceError(Exception)`
  - `src.source.yfinance_source._row_to_candidate(row: dict) -> Candidate | None` — pure; `None` means "not a qualifying common-stock 52-week high"

- [ ] **Step 1: Write the failing test**

```python
# tests/test_source_parse.py
from src.source.base import Candidate
from src.source.yfinance_source import _row_to_candidate

def row(**over):
    base = {
        "symbol": "AAPL", "shortName": "Apple Inc.", "exchange": "NMS",
        "quoteType": "EQUITY", "regularMarketPrice": 250.0,
        "regularMarketChangePercent": 1.8, "regularMarketDayHigh": 252.0,
        "fiftyTwoWeekHigh": 252.0, "marketCap": 3.9e12,
    }
    base.update(over)
    return base

def test_new_high_row_parses():
    c = _row_to_candidate(row())
    assert c == Candidate("AAPL", "Apple Inc.", "NASDAQ", 250.0, 1.8,
                          3.9e12, 252.0, "EQUITY")

def test_not_at_high_is_dropped():
    assert _row_to_candidate(row(regularMarketDayHigh=240.0)) is None

def test_day_cumulative_high_kept_even_after_pullback():
    # broke out earlier today (day high == 52wk high), pulled back to 245
    assert _row_to_candidate(row(regularMarketPrice=245.0)) is not None

def test_non_equity_dropped():
    assert _row_to_candidate(row(quoteType="ETF")) is None

def test_excluded_name_dropped():
    assert _row_to_candidate(row(shortName="Foo Acquisition Corp")) is None

def test_missing_field_dropped():
    assert _row_to_candidate(row(marketCap=None)) is None
    r = row(); del r["fiftyTwoWeekHigh"]
    assert _row_to_candidate(r) is None

def test_exchange_mapping():
    assert _row_to_candidate(row(exchange="NYQ")).exchange == "NYSE"
    assert _row_to_candidate(row(exchange="ASE")).exchange == "AMEX"
    assert _row_to_candidate(row(exchange="???")).exchange == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_source_parse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.source.base'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/source/base.py
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
```

```python
# src/source/yfinance_source.py
import config
from src.source.base import Candidate

# Yahoo exchange codes -> TradingView prefixes chart-img understands
_EXCHANGES = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ",
              "NYQ": "NYSE", "ASE": "AMEX"}
_REQUIRED = ("symbol", "regularMarketPrice", "regularMarketDayHigh",
             "fiftyTwoWeekHigh", "marketCap")

def _row_to_candidate(row: dict) -> Candidate | None:
    if any(row.get(k) is None for k in _REQUIRED):
        return None
    if row.get("quoteType") != "EQUITY":
        return None
    name = row.get("longName") or row.get("shortName") or ""
    if not name or config.NAME_EXCLUDE_RE.search(name):
        return None
    # Day-cumulative 52wk-high test: today's high touched the 52wk high.
    # Yahoo's fiftyTwoWeekHigh already includes today, so equality == new high.
    if row["regularMarketDayHigh"] + 1e-6 < row["fiftyTwoWeekHigh"]:
        return None
    return Candidate(
        ticker=row["symbol"],
        name=name,
        exchange=_EXCHANGES.get(row.get("exchange"), ""),
        price=float(row["regularMarketPrice"]),
        pct_change_today=float(row.get("regularMarketChangePercent") or 0.0),
        market_cap=float(row["marketCap"]),
        week52_high=float(row["fiftyTwoWeekHigh"]),
        security_type=row["quoteType"],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_source_parse.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/source tests/test_source_parse.py
git commit -m "feat: Candidate model and yfinance row parsing with 52wk-high rule"
```

---

### Task 3: State — posted log, trading-day math, cooldown, market hours

**Files:**
- Create: `src/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `config.MARKET_TZ`, `config.MARKET_OPEN`, `config.MARKET_CLOSE`
- Produces (all in `src.state`):
  - `load_posted(path: Path) -> list[dict]` — `[]` if file missing; entries `{"ticker": str, "date": "YYYY-MM-DD", "post_id": str|None}`
  - `append_posted(path: Path, ticker: str, day: date, post_id: str|None) -> None` — read-modify-write, creates file/dirs
  - `previous_trading_day(d: date) -> date` — skips Sat/Sun
  - `is_blocked(ticker: str, posted: list[dict], today: date) -> bool`
  - `daily_count(posted: list[dict], today: date) -> int`
  - `is_market_hours(now_utc: datetime) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: FAIL with `ImportError` / `ModuleNotFoundError` on `src.state`

- [ ] **Step 3: Write minimal implementation**

```python
# src/state.py
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import config

def load_posted(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    return json.loads(Path(path).read_text())["posts"]

def append_posted(path: Path, ticker: str, day: date, post_id: str | None) -> None:
    path = Path(path)
    posts = load_posted(path)
    posts.append({"ticker": ticker, "date": day.isoformat(), "post_id": post_id})
    path.parent.mkdir(parents=True, exist_ok=True)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat: posted-log state, consecutive-trading-day cooldown, market-hours gate"
```

---

### Task 4: Selection — validation gate, filters, ranking, caps

**Files:**
- Create: `src/select.py`
- Test: `tests/test_select.py`

**Interfaces:**
- Consumes: `Candidate` (Task 2), `state.is_blocked`/`state.daily_count` (Task 3), `config` caps
- Produces (in `src.select`):
  - `ValidationError(Exception)`
  - `validate(candidates: list[Candidate]) -> None` — raises if `len > config.MAX_PLAUSIBLE_HIGHS`
  - `pick(candidates: list[Candidate], posted: list[dict], today: date) -> list[Candidate]` — mcap floor + cooldown filter, mcap-desc rank, capped at `min(MAX_PER_TICK, MAX_PER_DAY - daily_count)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_select.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_select.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.select'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/select.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_select.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/select.py tests/test_select.py
git commit -m "feat: selection with validation gate, mcap ranking, tick and daily caps"
```

---

### Task 5: Publisher interface, post text, dry-run publisher

**Files:**
- Create: `src/publish/base.py`, `src/publish/dryrun.py`
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `Candidate` (Task 2)
- Produces:
  - `src.publish.base.PostResult` — dataclass `post_id: str | None, dry_run: bool`
  - `src.publish.base.Publisher` — ABC with `post(self, candidate: Candidate, text: str, image_png: bytes) -> PostResult`
  - `src.publish.base.compose_post_text(c: Candidate) -> str` — starts with `$TICKER` cashtag
  - `src.publish.dryrun.DryRunPublisher(out_dir: Path, today: date)` — writes `<out_dir>/<YYYY-MM-DD>/<TICKER>.png` and `.txt`
  - (Phase 2 adds `src/publish/stocktwits.py` implementing the same ABC — out of scope here)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish.py
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
    assert (day / "AAPL.txt").read_text() == "$AAPL hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_publish.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.publish.base'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/publish/base.py
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
```

```python
# src/publish/dryrun.py
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
        (self.day_dir / f"{candidate.ticker}.txt").write_text(text)
        return PostResult(post_id=None, dry_run=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_publish.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/publish tests/test_publish.py
git commit -m "feat: publisher interface, post-text template, dry-run publisher"
```

---

### Task 6: Chart client (chart-img.com)

**Files:**
- Create: `src/chart.py`
- Test: `tests/test_chart.py`

**Interfaces:**
- Consumes: `Candidate` (Task 2), `config.CHART_IMG_URL`
- Produces (in `src.chart`):
  - `ChartError(Exception)`
  - `fetch_chart_png(candidate: Candidate, api_key: str) -> bytes` — raises `ChartError` on any non-200/network failure
  - `_request_args(candidate: Candidate, api_key: str) -> tuple[str, dict, dict]` — pure `(url, params, headers)` builder

Note: param names below follow chart-img's v1 advanced-chart docs (symbol/interval/range/width/height/theme, `x-api-key` header). The Task 9 contract test verifies them against the live API; if the live API disagrees, fix `_request_args` there — unit tests here pin our contract, not theirs.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chart.py
import pytest
import requests
import config
from src import chart
from src.source.base import Candidate

CAND = Candidate("AAPL", "Apple Inc.", "NASDAQ", 250.0, 1.8, 3.9e12, 252.0, "EQUITY")

def test_request_args():
    url, params, headers = chart._request_args(CAND, "k3y")
    assert url == config.CHART_IMG_URL
    assert params["symbol"] == "NASDAQ:AAPL"
    assert params["interval"] == "1D"
    assert params["range"] == "12M"
    assert headers == {"x-api-key": "k3y"}

def test_request_args_no_exchange_falls_back_to_bare_ticker():
    c = Candidate("FOO", "Foo Inc", "", 10.0, 1.0, 2e9, 11.0, "EQUITY")
    _, params, _ = chart._request_args(c, "k")
    assert params["symbol"] == "FOO"

class FakeResp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content

def test_fetch_returns_bytes_on_200(monkeypatch):
    monkeypatch.setattr(requests, "get",
                        lambda url, params, headers, timeout: FakeResp(200, b"PNG!"))
    assert chart.fetch_chart_png(CAND, "k") == b"PNG!"

def test_fetch_raises_chart_error_on_429(monkeypatch):
    monkeypatch.setattr(requests, "get",
                        lambda url, params, headers, timeout: FakeResp(429))
    with pytest.raises(chart.ChartError):
        chart.fetch_chart_png(CAND, "k")

def test_fetch_raises_chart_error_on_network_failure(monkeypatch):
    def boom(url, params, headers, timeout):
        raise requests.ConnectionError("nope")
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(chart.ChartError):
        chart.fetch_chart_png(CAND, "k")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_chart.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.chart'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/chart.py
import requests

import config
from src.source.base import Candidate

class ChartError(Exception):
    """Chart service failed for this ticker; skip it this tick (stays eligible)."""

def _request_args(candidate: Candidate, api_key: str) -> tuple[str, dict, dict]:
    symbol = (f"{candidate.exchange}:{candidate.ticker}"
              if candidate.exchange else candidate.ticker)
    params = {"symbol": symbol, "interval": "1D", "range": "12M",
              "width": 800, "height": 450, "theme": "light"}
    return config.CHART_IMG_URL, params, {"x-api-key": api_key}

def fetch_chart_png(candidate: Candidate, api_key: str) -> bytes:
    url, params, headers = _request_args(candidate, api_key)
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise ChartError(f"{candidate.ticker}: {e}") from e
    if resp.status_code != 200:
        raise ChartError(f"{candidate.ticker}: chart-img returned {resp.status_code}")
    return resp.content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_chart.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/chart.py tests/test_chart.py
git commit -m "feat: chart-img client with 1-year chart params and ChartError"
```

---

### Task 7: yfinance live fetch (screen + quote filter)

**Files:**
- Modify: `src/source/yfinance_source.py` (add `YFinanceSource` below `_row_to_candidate`)
- Test: `tests/test_yfinance_source.py`

**Interfaces:**
- Consumes: `HighsSource`, `SourceError`, `_row_to_candidate` (Task 2)
- Produces: `src.source.yfinance_source.YFinanceSource` — implements `HighsSource.fetch_candidates() -> list[Candidate]`; raises `SourceError` if the screen returns zero quotes overall (broken feed ≠ zero highs). Internal seam `_screen_rows(self) -> list[dict]` does all network I/O so tests can fake it.

Known limitation (documented, acceptable for v1): Yahoo's screener paginates 250/page and may cap usable offsets; we sort by market cap descending so any truncation costs only the smallest names, and we rank by largest cap anyway. The Task 9 contract test measures actual coverage; the FMP swap in the spec backlog is the real fix.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yfinance_source.py
import pytest
from src.source.base import SourceError
from src.source.yfinance_source import YFinanceSource

def good_row(sym, day_high, wk_high):
    return {"symbol": sym, "shortName": f"{sym} Inc", "exchange": "NYQ",
            "quoteType": "EQUITY", "regularMarketPrice": day_high - 1,
            "regularMarketChangePercent": 1.0, "regularMarketDayHigh": day_high,
            "fiftyTwoWeekHigh": wk_high, "marketCap": 5e9}

def test_fetch_filters_to_new_highs(monkeypatch):
    src = YFinanceSource()
    rows = [good_row("HI", 101.0, 101.0),      # at 52wk high -> candidate
            good_row("LO", 90.0, 101.0)]       # not at high -> dropped
    monkeypatch.setattr(src, "_screen_rows", lambda: rows)
    got = src.fetch_candidates()
    assert [c.ticker for c in got] == ["HI"]

def test_fetch_raises_source_error_on_empty_screen(monkeypatch):
    src = YFinanceSource()
    monkeypatch.setattr(src, "_screen_rows", lambda: [])
    with pytest.raises(SourceError):
        src.fetch_candidates()

def test_zero_highs_from_nonempty_screen_is_fine(monkeypatch):
    src = YFinanceSource()
    monkeypatch.setattr(src, "_screen_rows", lambda: [good_row("LO", 90.0, 101.0)])
    assert src.fetch_candidates() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_yfinance_source.py -v`
Expected: FAIL with `ImportError: cannot import name 'YFinanceSource'`

- [ ] **Step 3: Write minimal implementation** (append to `src/source/yfinance_source.py`)

```python
import yfinance as yf

from src.source.base import HighsSource, SourceError
# `config` and `_row_to_candidate` are already in scope from the top of this file (Task 2)

_PAGE = 250
_MAX_OFFSET = 3000  # safety backstop; ~2-3k US names clear the $1B floor

class YFinanceSource(HighsSource):
    """Screen US equities >$1B by mcap desc, keep rows on today's 52wk-high list."""

    def _screen_rows(self) -> list[dict]:
        q = yf.EquityQuery("and", [
            yf.EquityQuery("eq", ["region", "us"]),
            yf.EquityQuery("gt", ["intradaymarketcap", config.MIN_MARKET_CAP]),
        ])
        rows, offset = [], 0
        while offset < _MAX_OFFSET:
            resp = yf.screen(q, offset=offset, size=_PAGE,
                             sortField="intradaymarketcap", sortAsc=False)
            quotes = (resp or {}).get("quotes", [])
            rows.extend(quotes)
            if len(quotes) < _PAGE:
                break
            offset += _PAGE
        return rows

    def fetch_candidates(self) -> list:
        rows = self._screen_rows()
        if not rows:
            raise SourceError("Yahoo screen returned zero quotes; feed looks broken")
        return [c for c in (_row_to_candidate(r) for r in rows) if c is not None]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_yfinance_source.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/source/yfinance_source.py tests/test_yfinance_source.py
git commit -m "feat: YFinanceSource live screen with pagination and SourceError gate"
```

---

### Task 8: Tick orchestration + CLI (`run.py`)

**Files:**
- Create: `run.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: everything above — `HighsSource`, `select.validate`/`select.pick`, `state.*`, `compose_post_text`, `Publisher`, `ChartError`
- Produces:
  - `run.tick(source, publisher, chart_fetch, state_path, now_utc, force=False) -> list[str]` — tickers posted this tick; `chart_fetch(candidate) -> bytes` is injected for testability
  - CLI: `python run.py [--force] [--state state/posted.json] [--output output]` — wires `YFinanceSource` + `DryRunPublisher` + real chart client (needs `CHART_IMG_API_KEY` env var); exits 0 on quiet tick, exits 1 on `SourceError`/`ValidationError`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run.py
from datetime import datetime, timezone, date
import pytest
import run
from src.chart import ChartError
from src.source.base import Candidate, HighsSource
from src.publish.base import Publisher, PostResult
from src import state

NOW = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)  # Wed 10:00 ET, market open
TODAY = date(2026, 7, 1)

def cand(ticker, mcap=5e9):
    return Candidate(ticker, f"{ticker} Inc", "NYSE", 100.0, 2.0, mcap, 101.0, "EQUITY")

class FakeSource(HighsSource):
    def __init__(self, cands): self.cands = cands
    def fetch_candidates(self): return self.cands

class SpyPublisher(Publisher):
    def __init__(self): self.calls = []
    def post(self, candidate, text, image_png):
        self.calls.append((candidate.ticker, text, image_png))
        return PostResult(post_id=None, dry_run=True)

def test_tick_posts_top_candidates_and_records_state(tmp_path):
    sp = tmp_path / "posted.json"
    pub = SpyPublisher()
    got = run.tick(FakeSource([cand("BIG", 9e9), cand("MID", 5e9), cand("SM", 2e9)]),
                   pub, lambda c: b"PNG", sp, NOW)
    assert got == ["BIG", "MID"]                      # 2-per-tick cap, mcap order
    assert pub.calls[0][0] == "BIG"
    assert pub.calls[0][1].startswith("$BIG ")
    assert [e["ticker"] for e in state.load_posted(sp)] == ["BIG", "MID"]

def test_tick_outside_market_hours_is_noop(tmp_path):
    closed = datetime(2026, 7, 1, 22, 0, tzinfo=timezone.utc)  # 18:00 ET
    pub = SpyPublisher()
    got = run.tick(FakeSource([cand("BIG")]), pub, lambda c: b"PNG",
                   tmp_path / "p.json", closed)
    assert got == [] and pub.calls == []

def test_tick_force_overrides_hours(tmp_path):
    closed = datetime(2026, 7, 1, 22, 0, tzinfo=timezone.utc)
    got = run.tick(FakeSource([cand("BIG")]), SpyPublisher(), lambda c: b"PNG",
                   tmp_path / "p.json", closed, force=True)
    assert got == ["BIG"]

def test_chart_failure_skips_ticker_and_continues(tmp_path):
    def flaky(c):
        if c.ticker == "BIG":
            raise ChartError("boom")
        return b"PNG"
    pub = SpyPublisher()
    got = run.tick(FakeSource([cand("BIG", 9e9), cand("MID", 5e9)]),
                   pub, flaky, tmp_path / "p.json", NOW)
    assert got == ["MID"]                    # BIG skipped, stays unposted/eligible
    posted = state.load_posted(tmp_path / "p.json")
    assert [e["ticker"] for e in posted] == ["MID"]

def test_second_tick_same_day_respects_cooldown(tmp_path):
    sp = tmp_path / "posted.json"
    src = FakeSource([cand("BIG", 9e9), cand("MID", 5e9), cand("SM", 2e9)])
    run.tick(src, SpyPublisher(), lambda c: b"PNG", sp, NOW)
    got2 = run.tick(src, SpyPublisher(), lambda c: b"PNG", sp, NOW)
    assert got2 == ["SM"]                    # BIG/MID posted today -> blocked
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'run'`

- [ ] **Step 3: Write minimal implementation**

```python
# run.py
"""One tick: source -> validate -> pick -> chart -> publish -> record."""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from src import select, state
from src.chart import ChartError, fetch_chart_png
from src.publish.base import Publisher, compose_post_text
from src.publish.dryrun import DryRunPublisher
from src.source.base import HighsSource, SourceError
from src.source.yfinance_source import YFinanceSource

def tick(source: HighsSource, publisher: Publisher, chart_fetch,
         state_path: Path, now_utc: datetime, force: bool = False) -> list[str]:
    if not force and not state.is_market_hours(now_utc):
        print("outside market hours; nothing to do")
        return []
    today = now_utc.astimezone(ZoneInfo(config.MARKET_TZ)).date()

    candidates = source.fetch_candidates()
    select.validate(candidates)
    posted = state.load_posted(state_path)
    picks = select.pick(candidates, posted, today)
    print(f"{len(candidates)} on today's 52wk-high list; posting {len(picks)}")

    done: list[str] = []
    for c in picks:
        try:
            png = chart_fetch(c)
        except ChartError as e:
            print(f"chart failed, skipping {c.ticker}: {e}")
            continue
        result = publisher.post(c, compose_post_text(c), png)
        state.append_posted(state_path, c.ticker, today, result.post_id)
        done.append(c.ticker)
        print(f"posted {c.ticker} (dry_run={result.dry_run})")
    return done

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="run even outside market hours (local testing)")
    ap.add_argument("--state", default="state/posted.json", type=Path)
    ap.add_argument("--output", default="output", type=Path)
    args = ap.parse_args()

    api_key = os.environ.get("CHART_IMG_API_KEY", "")
    if not api_key:
        print("CHART_IMG_API_KEY not set", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(config.MARKET_TZ)).date()
    publisher = DryRunPublisher(args.output, today)  # Phase 2: swap for Stocktwits
    try:
        tick(YFinanceSource(), publisher,
             lambda c: fetch_chart_png(c, api_key), args.state, now, args.force)
    except (SourceError, select.ValidationError) as e:
        print(f"aborted: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Note for the implementer: `main()` intentionally has no unit tests (it's argparse + env wiring); `tick()` carries the logic and is fully tested. Do not add tests that call the network.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_run.py -v`
Expected: 5 passed

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest -v`
Expected: all tests pass, 0 failures

- [ ] **Step 6: Commit**

```bash
git add run.py tests/test_run.py
git commit -m "feat: tick orchestration and CLI entrypoint"
```

---

### Task 9: Contract tests (manual-only, live APIs)

**Files:**
- Create: `tests/contract/__init__.py`, `tests/contract/test_live_yfinance.py`, `tests/contract/test_live_chart_img.py`

**Interfaces:**
- Consumes: `YFinanceSource` (Task 7), `chart.fetch_chart_png` (Task 6)
- Produces: nothing downstream — these verify our assumptions about external APIs. Marked `@pytest.mark.contract`, excluded by default (`addopts = -m 'not contract'` from Task 1).

- [ ] **Step 1: Write the contract tests**

```python
# tests/contract/__init__.py  (empty)
```

```python
# tests/contract/test_live_yfinance.py
"""Run manually on a market day: pytest -m contract tests/contract/test_live_yfinance.py -v"""
import pytest
from src.source.yfinance_source import YFinanceSource

pytestmark = pytest.mark.contract

def test_screen_returns_plausible_universe_and_highs():
    src = YFinanceSource()
    rows = src._screen_rows()
    # coverage check for the documented pagination-cap limitation
    assert len(rows) > 500, f"screen coverage suspiciously low: {len(rows)} rows"
    cands = src.fetch_candidates()
    assert 0 <= len(cands) < 500
    if cands:
        c = cands[0]
        assert c.ticker and c.market_cap >= 1e9 and c.week52_high > 0
        print(f"\n{len(rows)} screened, {len(cands)} on today's 52wk-high list; "
              f"top: {[x.ticker for x in cands[:10]]}")
```

```python
# tests/contract/test_live_chart_img.py
"""Run manually: CHART_IMG_API_KEY=... pytest -m contract tests/contract/test_live_chart_img.py -v"""
import os
import pytest
from src.chart import fetch_chart_png
from src.source.base import Candidate

pytestmark = pytest.mark.contract

def test_live_chart_is_a_real_png():
    key = os.environ.get("CHART_IMG_API_KEY")
    if not key:
        pytest.skip("CHART_IMG_API_KEY not set")
    c = Candidate("AAPL", "Apple Inc.", "NASDAQ", 0, 0, 0, 0, "EQUITY")
    png = fetch_chart_png(c, key)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"   # PNG magic bytes
    assert len(png) > 10_000                  # a real chart, not an error blob
```

- [ ] **Step 2: Verify they are excluded from the default run**

Run: `python3 -m pytest -v`
Expected: all unit tests pass; contract tests shown as **deselected** (or absent), none executed.

- [ ] **Step 3: Run the yfinance contract test live (any market day)**

Run: `python3 -m pytest -m contract tests/contract/test_live_yfinance.py -v -s`
Expected: PASS with a printed universe/highs count. If it fails on `yf.screen` signature or coverage, fix `_screen_rows` (Task 7) to match reality — that is this test's job. (chart-img test runs once an API key exists; get a free-tier key at chart-img.com.)

- [ ] **Step 4: Commit**

```bash
git add tests/contract
git commit -m "test: manual contract tests for live yfinance and chart-img"
```

---

### Task 10: GitHub Actions — tick cron + CI + README

**Files:**
- Create: `.github/workflows/tick.yml`, `.github/workflows/ci.yml`, `README.md`

**Interfaces:**
- Consumes: `run.py` CLI (Task 8); repo secret `CHART_IMG_API_KEY` (added manually in GitHub settings)
- Produces: scheduled dry-run posts committed to `output/` + `state/posted.json` (Phase 1 resolves the spec's open question: output IS committed, so runs are eyeballable from GitHub)

- [ ] **Step 1: Write the tick workflow**

```yaml
# .github/workflows/tick.yml
name: tick
on:
  schedule:
    # Every 30 min, 13:00-21:59 UTC weekdays. Covers 9:30am-4pm ET in both
    # EDT (13:30-20:00 UTC) and EST (14:30-21:00 UTC); run.py gates precisely.
    - cron: "*/30 13-21 * * 1-5"
  workflow_dispatch: {}

permissions:
  contents: write

concurrency:
  group: tick
  cancel-in-progress: false

jobs:
  tick:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - name: Run tick
        env:
          CHART_IMG_API_KEY: ${{ secrets.CHART_IMG_API_KEY }}
        run: python run.py
      - name: Commit state + output
        run: |
          git config user.name "52wk-poster-bot"
          git config user.email "actions@users.noreply.github.com"
          git add state output
          if git diff --cached --quiet; then
            echo "nothing posted this tick"; exit 0
          fi
          git commit -m "state: tick $(date -u +'%Y-%m-%dT%H:%M')"
          git pull --rebase origin main
          git push
```

- [ ] **Step 2: Write the CI workflow**

```yaml
# .github/workflows/ci.yml
name: ci
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements-dev.txt
      - run: python -m pytest -v
```

- [ ] **Step 3: Write the README**

```markdown
# stocktwits-52wk-poster

Posts curated 52-week-high calls to Stocktwits through the trading day:
any US common stock >$1B that hit a new 52-week high **at some point today**
is a candidate; every 30 minutes the top names by market cap (max 2/tick,
20/day, never on consecutive trading days) get a 1-year chart + $TICKER post.

**Phase 1 (current):** dry-run publisher — each tick writes what *would* be
posted to `output/YYYY-MM-DD/` and commits it. **Phase 2:** real Stocktwits
API publisher (`src/publish/stocktwits.py`), pending API access.

## Pipeline (one tick)

yfinance screen (US, >$1B, mcap-desc) → today's 52wk-high list →
filters + cooldown + caps (`src/select.py`) → chart-img 1-yr PNG
(`src/chart.py`) → publisher (`src/publish/`) → `state/posted.json`.

## Run locally

    pip install -r requirements-dev.txt
    python -m pytest                              # unit tests
    CHART_IMG_API_KEY=... python run.py --force   # one tick, any time of day
    python -m pytest -m contract -v -s            # live-API contract tests

## Ops

- Cron: `.github/workflows/tick.yml`, every 30 min during market hours.
  A failed tick emails via GitHub; missing one tick is harmless.
- Secret required: `CHART_IMG_API_KEY` (repo → Settings → Secrets → Actions).
- All knobs live in `config.py`.
- Spec + deferred backlog: `docs/superpowers/specs/2026-07-01-stocktwits-52wk-poster-design.md`.
```

- [ ] **Step 4: Validate workflow syntax + full suite**

Run: `python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]" && python3 -m pytest -q`
Expected: no YAML errors; all unit tests pass. (If PyYAML isn't installed: `pip install pyyaml` or skip the YAML check — Actions will validate on push.)

- [ ] **Step 5: Commit**

```bash
git add .github README.md
git commit -m "ci: 30-min market-hours tick workflow, CI tests, README"
```

---

## Post-plan checklist (not tasks — operator actions)

1. Create GitHub repo (e.g. `ethanberrk/stocktwits-52wk-poster`), push `main`.
2. Get a chart-img.com API key (free tier to start; check request quota covers ~20-40 charts/day) and add repo secret `CHART_IMG_API_KEY`.
3. Trigger `tick` via workflow_dispatch on a market day; eyeball `output/YYYY-MM-DD/`.
4. When Stocktwits API access arrives → Phase 2 plan (new spec section + plan for `src/publish/stocktwits.py`, auth secret, config flip).

## Self-review notes

- **Spec coverage:** source ✓(T2,T7), select/caps/cooldown ✓(T3,T4), chart ✓(T6), publisher/dry-run ✓(T5), orchestration + market-hours gate ✓(T8), validation gate ✓(T4,T7), state commit-back ✓(T10), contract tests ✓(T9), CI ✓(T10). Phase 2 (Stocktwits client) intentionally out of scope.
- **Deviations from spec, all flagged inline:** single state file with derived daily count; `Candidate.exchange` added; `output/` committed (resolves open question).
- **Type consistency:** `Candidate` field order (ticker, name, exchange, price, pct_change_today, market_cap, week52_high, security_type) is identical in every positional construction across T2, T5, T6, T8, T9; `pick(candidates, posted, today)` and `tick(source, publisher, chart_fetch, state_path, now_utc, force)` signatures match between definition and all call sites.
