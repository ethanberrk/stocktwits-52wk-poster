# Self-Rendered Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the chart-img.com API with an in-process matplotlib renderer ported from `stocktwits-relative-strength-poster`, removing the `CHART_IMG_API_KEY` dependency.

**Architecture:** `src/chart.py` is swapped wholesale: instead of POSTing to chart-img, it fetches 1Y daily OHLC from stockanalysis.com (keyless, via a new urllib helper `src/fetch.py`), appends today's candle from the live quote, and draws a TradingView-style 800×450 candlestick PNG with matplotlib. The public contract is unchanged except the signature loses its `api_key` parameter: `fetch_chart_png(candidate) -> bytes`, raising `ChartError` on any failure (tick loop already skips that ticker and it stays eligible).

**Tech Stack:** Python 3.12, matplotlib (Agg backend), urllib (NOT requests), pytest.

**Spec:** `docs/superpowers/specs/2026-07-10-self-rendered-charts-design.md`

## Global Constraints

- Run all tests via `.venv/bin/python -m pytest` (the global python's yfinance is too old for other tests in this suite).
- All new HTTP goes through urllib, never `requests` (Stocktwits'/some CDNs 403-block requests' TLS fingerprint; repo-wide stance).
- Live posts are undeletable. NEVER run `run.py --live` locally, and NEVER point a local test run at the real `state/posted.json` or `output/` — always pass `--state` and `--output` scratch paths.
- The contract-test marker setup (`-m contract`, excluded from the default run) already exists in this repo — reuse it, don't reconfigure.
- Work on branch `feat/self-rendered-charts`.
- Reference implementation being ported: `/Users/ethanberk/stocktwits-relative-strength-poster` `src/chart.py`, `src/fetch.py`, `tests/test_chart.py`. Code in this plan is already adapted for THIS repo (its `Candidate` has no `watchers`/`pct` fields in the same shape) — copy from the plan, not from that repo.

---

### Task 1: `src/fetch.py` — keyless JSON-over-HTTP helper

**Files:**
- Create: `src/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Produces: `get_json(url, opener=None, tries=4) -> dict | list | None` — parsed JSON on success; `None` after exhausting retries (429/503 retried with backoff, non-retryable HTTP errors return `None` immediately). Task 3's chart module imports it as `from src.fetch import get_json`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fetch.py`:

```python
import io
import json
import urllib.error

from src.fetch import get_json


class _FakeOpener:
    """Stands in for urllib's opener: returns queued responses/exceptions."""
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def open(self, req, timeout=None):
        self.calls += 1
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return io.BytesIO(json.dumps(r).encode())


def test_get_json_returns_parsed_body():
    opener = _FakeOpener([{"data": {"p": 42.0}}])
    assert get_json("https://x.test/q", opener=opener) == {"data": {"p": 42.0}}


def test_get_json_retries_on_429_then_succeeds():
    err = urllib.error.HTTPError("u", 429, "too many", {}, None)
    opener = _FakeOpener([err, {"ok": 1}])
    assert get_json("https://x.test/q", opener=opener) == {"ok": 1}
    assert opener.calls == 2


def test_get_json_returns_none_on_404():
    err = urllib.error.HTTPError("u", 404, "nope", {}, None)
    opener = _FakeOpener([err])
    assert get_json("https://x.test/q", opener=opener) is None


def test_get_json_returns_none_when_all_tries_fail():
    opener = _FakeOpener([ConnectionError("x")] * 4)
    assert get_json("https://x.test/q", opener=opener, tries=4) is None
    assert opener.calls == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.fetch'`

- [ ] **Step 3: Create `src/fetch.py`**

Copied from the RS poster (verbatim; retry sleeps are short by design):

```python
"""Shared JSON-over-HTTP helper. urllib on purpose (see src/stocktwits.py):
some CDNs 403 the requests TLS fingerprint but pass urllib."""
import json
import time
import urllib.error
import urllib.request

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def get_json(url, opener=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            fh = (opener.open(req, timeout=12) if opener
                  else urllib.request.urlopen(req, timeout=12))
            with fh as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(1.5 * (i + 1)); continue
            return None
        except Exception:
            time.sleep(0.5 * (i + 1))
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_fetch.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/fetch.py tests/test_fetch.py
git commit -m "feat: keyless JSON-over-HTTP helper (urllib, retries)"
```

---

### Task 2: config — stockanalysis endpoints + chart knobs, drop CHART_IMG_URL

**Files:**
- Modify: `config.py` (the `CHART_IMG_URL` block, ~lines 14–16)
- Test: `tests/test_config.py` (append)

**Interfaces:**
- Produces: `config.SA_QUOTE_URL`, `config.SA_HISTORY_URL` (format-string URLs with `{ticker}`), `config.MIN_HISTORY_DAYS = 330`, `config.CHART_WIDTH = 800`, `config.CHART_HEIGHT = 450`. `config.CHART_IMG_URL` no longer exists.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_chart_source_config():
    # keyless stockanalysis endpoints drive the self-rendered charts
    assert "{ticker}" in config.SA_QUOTE_URL
    assert "{ticker}" in config.SA_HISTORY_URL
    assert "range=1Y" in config.SA_HISTORY_URL
    assert "period=Daily" in config.SA_HISTORY_URL
    assert config.MIN_HISTORY_DAYS == 330
    assert (config.CHART_WIDTH, config.CHART_HEIGHT) == (800, 450)
    # chart-img is gone entirely
    assert not hasattr(config, "CHART_IMG_URL")
```

(If `tests/test_config.py` does not already `import config` at top, add it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: new test FAILS with `AttributeError: ... SA_QUOTE_URL`

- [ ] **Step 3: Edit `config.py`**

Replace this block:

```python
# v2 (POST + JSON body): the only version exposing `session`, which we pin to
# "regular" so a chart captured at the open never shows a pre-market price line.
CHART_IMG_URL = "https://api.chart-img.com/v2/tradingview/advanced-chart"
```

with:

```python
# Self-rendered charts: keyless daily-OHLC history + live quote from
# stockanalysis.com (same source the relative-strength poster runs on).
SA_QUOTE_URL = "https://stockanalysis.com/api/quotes/s/{ticker}"
SA_HISTORY_URL = ("https://stockanalysis.com/api/symbol/s/{ticker}/history"
                  "?range=1Y&period=Daily")
MIN_HISTORY_DAYS = 330      # refuse a "1Y" chart for a recent IPO with less
                            # than ~11 months of candles — it would mislead
CHART_WIDTH = 800           # px; matches the size chart-img produced
CHART_HEIGHT = 450
```

- [ ] **Step 4: Run config tests**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: all PASS. (`tests/test_chart.py` is now broken — it still tests the chart-img client. That is expected; Task 3 replaces it. Do NOT run the full suite at this step.)

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: config for self-rendered charts, drop CHART_IMG_URL"
```

---

### Task 3: replace `src/chart.py` with the matplotlib renderer

**Files:**
- Rewrite: `src/chart.py`
- Rewrite: `tests/test_chart.py`

**Interfaces:**
- Consumes: `src.fetch.get_json` (Task 1), `config.SA_*`/`MIN_HISTORY_DAYS`/`CHART_*` (Task 2), `src.source.base.Candidate` (existing: fields `ticker, name, exchange, price, pct_change_today, market_cap, week52_high, security_type`).
- Produces: `fetch_chart_png(candidate: Candidate) -> bytes` (PNG), `ChartError(Exception)`. **Note the signature change**: no `api_key` — Task 4 rewires `run.py`.

- [ ] **Step 1: Rewrite `tests/test_chart.py` (failing tests)**

Replace the whole file (ported from the RS repo; `_c()` adapted to this repo's `Candidate`):

```python
from datetime import date

import pytest

from src import chart
from src.source.base import Candidate


def _c(ticker="ABCD", exchange="NASDAQ"):
    return Candidate(ticker=ticker, name="x", exchange=exchange, price=1.0,
                     pct_change_today=0.0, market_cap=2e9, week52_high=1.0,
                     security_type="EQUITY")


def _ohlc(n=60):
    rows, px = [], 20.0
    for i in range(n):
        o = px
        c = px * (1.02 if i % 3 else 0.985)
        rows.append([f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                     o, max(o, c) * 1.01, min(o, c) * 0.99, c])
        px = c
    return rows


def test_render_png_returns_png_bytes():
    png = chart._render_png(_c(), _ohlc())
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5_000


def test_fetch_history_appends_today_candle_when_stale(monkeypatch):
    def fake_get_json(url, **kw):
        if "history" in url:
            return {"data": [{"t": "2025-07-10", "o": 20.0, "h": 20.5,
                              "l": 19.8, "c": 20.2},
                             {"t": "2026-07-08", "o": 37.0, "h": 37.5,
                              "l": 35.1, "c": 37.47}]}
        if "api/quotes" in url:
            return {"data": {"p": 42.39, "o": 38.33, "h": 42.67, "l": 38.26}}
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(chart, "get_json", fake_get_json)
    rows = chart._fetch_history("TXG", today=date(2026, 7, 9))
    assert rows[-1] == ["2026-07-09", 38.33, 42.67, 38.26, 42.39]
    assert rows[0][0] == "2025-07-10"


def test_fetch_history_no_append_when_current(monkeypatch):
    def fake_get_json(url, **kw):
        if "history" in url:
            return {"data": [{"t": "2025-07-10", "o": 20.0, "h": 20.5,
                              "l": 19.8, "c": 20.2},
                             {"t": "2026-07-09", "o": 38.0, "h": 42.7,
                              "l": 38.0, "c": 42.39}]}
        raise AssertionError("quote endpoint must not be hit")

    monkeypatch.setattr(chart, "get_json", fake_get_json)
    rows = chart._fetch_history("TXG", today=date(2026, 7, 9))
    assert len(rows) == 2 and rows[-1][0] == "2026-07-09"


def test_fetch_chart_png_raises_on_unavailable_history(monkeypatch):
    monkeypatch.setattr(chart, "get_json", lambda url, **kw: None)
    with pytest.raises(chart.ChartError):
        chart.fetch_chart_png(_c())


def test_fetch_chart_png_end_to_end(monkeypatch):
    monkeypatch.setattr(chart, "_fetch_history",
                        lambda ticker, today=None: _ohlc())
    png = chart.fetch_chart_png(_c())
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def _history_json(first_date, last=("2026-07-09", 38.0, 42.7, 38.0, 42.39)):
    t, o, h, l, c = last
    return {"data": [{"t": first_date, "o": 10.0, "h": 10.5, "l": 9.8, "c": 10.2},
                     {"t": t, "o": o, "h": h, "l": l, "c": c}]}


def test_fetch_history_rejects_recent_ipo(monkeypatch):
    monkeypatch.setattr(chart, "get_json",
                        lambda url, **kw: _history_json("2026-05-11"))
    with pytest.raises(chart.ChartError, match="2026-05-11"):
        chart._fetch_history("GMRS", today=date(2026, 7, 9))


def test_fetch_history_allows_year_old_history(monkeypatch):
    monkeypatch.setattr(chart, "get_json",
                        lambda url, **kw: _history_json("2025-07-10"))
    rows = chart._fetch_history("TXG", today=date(2026, 7, 9))
    assert rows[0][0] == "2025-07-10"


def test_fetch_history_allows_first_candle_exactly_at_cutoff(monkeypatch):
    # 330 days before 2026-07-09 is 2025-08-13: exactly at the cutoff passes.
    monkeypatch.setattr(chart, "get_json",
                        lambda url, **kw: _history_json("2025-08-13"))
    rows = chart._fetch_history("TXG", today=date(2026, 7, 9))
    assert rows[0][0] == "2025-08-13"


def test_legend_text_change_is_vs_previous_close():
    hist = [["2026-07-08", 20.0, 21.0, 19.5, 21.0],   # prev close 21.00
            ["2026-07-09", 22.0, 30.2, 20.9, 30.26]]  # gaps up to 22.00
    text = chart._legend_text(hist)
    assert "O 22.00" in text and "C 30.26" in text
    assert "+9.26 (+44.10%)" in text  # 30.26 vs prev CLOSE 21.00, not open


def test_legend_text_single_candle_uses_open():
    text = chart._legend_text([["2026-07-09", 20.0, 30.0, 20.0, 25.0]])
    assert "+5.00 (+25.00%)" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_chart.py -v`
Expected: FAIL — `AttributeError` (`chart._render_png`, `chart.get_json` etc. don't exist yet; the file still holds the chart-img client).

- [ ] **Step 3: Rewrite `src/chart.py`**

Replace the whole file (ported from the RS repo; only the `fetch_chart_png` signature and docstring differ):

```python
"""Self-rendered 1-year daily candlestick chart (matplotlib -> PNG bytes).

Replaces the chart-img API: history comes keyless from stockanalysis.com and
the chart is drawn in-process in the TradingView light style (up #089981,
down #F23645, recessive grid, right-hand price axis, last-price pill). The
daily history endpoint lags one session, so today's candle is appended from
the live quote — a 52wk-high post whose chart stopped yesterday would be
missing its own move.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import io

from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle

import config
from src.fetch import get_json
from src.source.base import Candidate

UP, DOWN = "#089981", "#F23645"
INK, MUTED, GRID = "#131722", "#787b86", "#e9edf1"
_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class ChartError(Exception):
    """Chart data/render failed for this ticker; skip it this tick (stays eligible)."""


def _fetch_history(ticker: str, today: date | None = None) -> list[list]:
    """[[YYYY-MM-DD, o, h, l, c], ...] ascending, ending with today's candle."""
    if today is None:
        today = datetime.now(ZoneInfo(config.MARKET_TZ)).date()
    d = get_json(config.SA_HISTORY_URL.format(ticker=ticker))
    rows = (d or {}).get("data") or []
    hist = sorted(([r["t"], r["o"], r["h"], r["l"], r["c"]] for r in rows),
                  key=lambda r: r[0])
    if not hist:
        raise ChartError(f"{ticker}: no daily history from stockanalysis")
    cutoff = (today - timedelta(days=config.MIN_HISTORY_DAYS)).isoformat()
    if hist[0][0] > cutoff:
        raise ChartError(
            f"{ticker}: history starts {hist[0][0]}, needs to reach back to "
            f"{cutoff} — likely a recent IPO, 1Y chart would mislead")
    if hist[-1][0] < today.isoformat():
        q = (get_json(config.SA_QUOTE_URL.format(ticker=ticker)) or {}).get("data")
        if q and q.get("p") and q.get("o"):
            p = float(q["p"])
            hist.append([today.isoformat(), float(q["o"]),
                         float(q.get("h") or p), float(q.get("l") or p), p])
    return hist


def _legend_text(hist: list[list]) -> str:
    """TradingView-style OHLC line; change is vs the PREVIOUS close (falls
    back to today's open on the first candle), matching how TradingView and
    quote pages report the day's move on gap days."""
    o, hi_d, lo_d, c = hist[-1][1:]
    base = hist[-2][4] if len(hist) > 1 else o
    chg = c - base
    return (f"1D · 1Y · O {o:,.2f}  H {hi_d:,.2f}  L {lo_d:,.2f}  C {c:,.2f}"
            f"  {chg:+,.2f} ({chg / base * 100:+.2f}%)")


def _render_png(candidate: Candidate, hist: list[list]) -> bytes:
    w, h = config.CHART_WIDTH / 100, config.CHART_HEIGHT / 100
    fig, ax = plt.subplots(figsize=(w, h), dpi=100)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(left=0.012, right=0.925, top=0.90, bottom=0.075)

    n = len(hist)
    body_w = max(0.55, min(0.7, 0.7))  # in index units; thin at 1Y density
    for i, (_, o, hi, lo, c) in enumerate(hist):
        col = UP if c >= o else DOWN
        ax.plot([i, i], [lo, hi], color=col, linewidth=0.7, zorder=2)
        ax.add_patch(Rectangle((i - body_w / 2, min(o, c)), body_w,
                               max(abs(c - o), 1e-9), facecolor=col,
                               edgecolor="none", zorder=3))

    # recessive grid + month boundaries
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=1)
    ticks, labels = [], []
    for i in range(1, n):
        m_prev, m_cur = hist[i - 1][0][5:7], hist[i][0][5:7]
        if m_prev != m_cur:
            ax.axvline(i - 0.5, color=GRID, linewidth=0.8, zorder=1)
            ticks.append(i - 0.5)
            labels.append(hist[i][0][:4] if m_cur == "01"
                          else _MONTHS[int(m_cur)])
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, fontsize=9, color=MUTED)

    ax.yaxis.tick_right()
    ax.tick_params(axis="y", labelsize=9, colors=MUTED, length=0)
    ax.tick_params(axis="x", colors=MUTED, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xlim(-1, n)
    lo = min(r[3] for r in hist)
    hi = max(r[2] for r in hist)
    pad = (hi - lo) * 0.06 or 1
    ax.set_ylim(lo - pad, hi + pad)

    # last-price dashed line + pill on the price axis
    last_o, last_c = hist[-1][1], hist[-1][4]
    lp_col = UP if last_c >= last_o else DOWN
    ax.axhline(last_c, color=lp_col, linewidth=0.8, linestyle=(0, (2, 2)),
               zorder=4)
    ax.annotate(f"{last_c:,.2f}", xy=(1.0, last_c),
                xycoords=("axes fraction", "data"), xytext=(4, 0),
                textcoords="offset points", fontsize=9, fontweight="bold",
                color="white", va="center", ha="left", zorder=5,
                bbox=dict(boxstyle="round,pad=0.28", facecolor=lp_col,
                          edgecolor="none"))

    # top-left legend, TradingView style
    fig.text(0.015, 0.955, f"{candidate.exchange}:{candidate.ticker}",
             fontsize=11, fontweight="bold", color=INK)
    fig.text(0.015 + 0.017 * len(f"{candidate.exchange}:{candidate.ticker}"),
             0.955, _legend_text(hist), fontsize=9.5, color=MUTED)

    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", facecolor="white")
    finally:
        plt.close(fig)
    return buf.getvalue()


def fetch_chart_png(candidate: Candidate) -> bytes:
    try:
        hist = _fetch_history(candidate.ticker)
    except ChartError:
        raise
    except Exception as e:
        raise ChartError(f"{candidate.ticker}: {e}") from e
    try:
        return _render_png(candidate, hist)
    except Exception as e:
        raise ChartError(f"{candidate.ticker}: render failed: {e}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_chart.py -v`
Expected: 10 PASS. If matplotlib is missing from `.venv`, run `.venv/bin/pip install "matplotlib>=3.8"` first (requirements.txt is updated in Task 4).

- [ ] **Step 5: Commit**

```bash
git add src/chart.py tests/test_chart.py
git commit -m "feat: self-rendered matplotlib chart, drop chart-img client"
```

---

### Task 4: wire-up — run.py, tick.yml, requirements

**Files:**
- Modify: `run.py:104-118` (the `main()` api-key block and tick call)
- Modify: `.github/workflows/tick.yml` (env block of the "Run tick" step)
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `fetch_chart_png(candidate) -> bytes` (Task 3).
- Produces: `run.py` no longer reads `CHART_IMG_API_KEY` anywhere.

- [ ] **Step 1: Edit `run.py`**

In `main()`, delete these lines:

```python
    api_key = os.environ.get("CHART_IMG_API_KEY", "")
    if not api_key:
        print("CHART_IMG_API_KEY not set", file=sys.stderr)
        return 1
```

and change the `tick(...)` call from:

```python
        tick(YFinanceSource(), publisher,
             lambda c: fetch_chart_png(c, api_key), args.state, now, args.force,
```

to:

```python
        tick(YFinanceSource(), publisher,
             fetch_chart_png, args.state, now, args.force,
```

(`os` stays imported — `build_publisher` still uses it.)

- [ ] **Step 2: Edit `.github/workflows/tick.yml`**

Delete this single line from the "Run tick" step's `env:` block:

```yaml
          CHART_IMG_API_KEY: ${{ secrets.CHART_IMG_API_KEY }}
```

(Leave the secret itself in place on GitHub until after merge — old main still needs it. Removal is Task 7.)

- [ ] **Step 3: Edit `requirements.txt`**

Replace the full contents with:

```
yfinance>=0.2.50
matplotlib>=3.8
```

(`requests` is dropped: `src/chart.py` was its only direct user; yfinance declares its own copy. `tests/test_publish.py` even asserts the publisher avoids it.)

Then sync the venv:

```bash
.venv/bin/pip install -r requirements.txt
```

- [ ] **Step 4: Run the FULL suite**

Run: `.venv/bin/python -m pytest -v`
Expected: all PASS, 0 failures — `tests/test_run.py` (fake chart_fetch callables, unaffected), fetch/config/chart from Tasks 1–3, and everything else untouched.

- [ ] **Step 5: Commit**

```bash
git add run.py .github/workflows/tick.yml requirements.txt
git commit -m "feat: wire self-rendered charts into tick; drop CHART_IMG_API_KEY"
```

---

### Task 5: contract test — live render replaces live chart-img

**Files:**
- Delete: `tests/contract/test_live_chart_img.py`
- Create: `tests/contract/test_live_chart_render.py`

**Interfaces:**
- Consumes: `fetch_chart_png(candidate) -> bytes` (Task 3).

- [ ] **Step 1: Delete the old contract test, create the new one**

```bash
git rm tests/contract/test_live_chart_img.py
```

Create `tests/contract/test_live_chart_render.py`:

```python
# tests/contract/test_live_chart_render.py
"""Run manually: pytest -m contract tests/contract/test_live_chart_render.py -v
Hits stockanalysis.com live (keyless) and renders a real chart."""
import pytest

from src.chart import fetch_chart_png
from src.source.base import Candidate

pytestmark = pytest.mark.contract


def test_live_render_is_a_real_png():
    c = Candidate("AAPL", "Apple Inc.", "NASDAQ", 0, 0, 0, 0, "EQUITY")
    png = fetch_chart_png(c)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"   # PNG magic bytes
    assert len(png) > 10_000                  # a real chart, not an error blob
```

- [ ] **Step 2: Run the contract test LIVE**

Run: `.venv/bin/python -m pytest -m contract tests/contract/test_live_chart_render.py -v`
Expected: 1 PASS (network required). Also confirm the default suite still skips it: `.venv/bin/python -m pytest` collects no `contract` tests.

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_live_chart_render.py
git commit -m "test: live-render contract test replaces chart-img one"
```

---

### Task 6: local dry-run tick against scratch state — eyeball real output

This is the spec's pre-merge verification. It hits live yfinance + Stocktwits
symbol-check + stockanalysis, but posts nothing (dry-run publisher) and must
not touch the repo's real `state/` or `output/`.

**Files:** none modified — verification only.

- [ ] **Step 1: Run a dry-run tick into scratch paths**

```bash
mkdir -p /tmp/52wk-chart-verify
.venv/bin/python run.py --force \
    --state /tmp/52wk-chart-verify/posted.json \
    --output /tmp/52wk-chart-verify/output
```

Expected: prints `N on today's 52wk-high list; posting M` then `posted <TICKER> (dry_run=True)` lines (M ≥ 1 on a trading day; on a weekend/holiday the source may return few or no candidates — if so, note it and verify with the Task 5 contract-test PNG instead).

- [ ] **Step 2: Eyeball the PNGs**

Open every `/tmp/52wk-chart-verify/output/<date>/<TICKER>.png` (Read tool / Preview). Verify each: candlesticks span a full year, months labeled on the x-axis, prices on the right axis, `EXCHANGE:TICKER` + OHLC legend top-left, dashed last-price line with pill, **no watermark**. Confirm `git status` shows a clean tree (no accidental writes to real `state/` or `output/`).

- [ ] **Step 3: Clean up scratch**

```bash
rm -rf /tmp/52wk-chart-verify
```

---

### Task 7: ship — PR, merge, then retire the secret

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin feat/self-rendered-charts
gh pr create --title "Self-rendered charts (drop chart-img API)" --body "..."
```

PR body: summarize the spec (link `docs/superpowers/specs/2026-07-10-self-rendered-charts-design.md`), note the deliberate behavior changes (new look, IPO skip, stockanalysis dependency) and the Task 6 verification result. End with the standard Claude Code attribution footer.

- [ ] **Step 2: Squash-merge after user approval** (repo pattern: PRs #1/#2 were squash-merged, branch deleted)

- [ ] **Step 3: AFTER merge only — delete the now-unused secret**

```bash
gh secret delete CHART_IMG_API_KEY -R ethanberrk/stocktwits-52wk-poster
```

Ordering matters: live ticks run tick.yml from main every 30 minutes during
market hours; the secret must outlive the old workflow. After merge, the next
dispatched tick uses the new chart path — watch its Actions log and the first
1–2 posts on @Stocktwits52wHighs.

- [ ] **Step 4: Remind the user (final summary items)**
  - They can cancel the chart-img.com plan — nothing references it anymore.
  - The chart-img key-rotation TODO is resolved by deletion; the Stocktwits token rotation is still open.
