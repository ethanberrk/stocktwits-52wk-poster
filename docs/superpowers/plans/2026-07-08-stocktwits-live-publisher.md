# Live Stocktwits Publisher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post each selected 52-week-high (`$TICKER` copy + 1-year TradingView chart PNG) to Stocktwits via the CORE `messages/create` API, replacing the Phase-1 dry-run publisher, behind a dry-run-by-default `--live` switch.

**Architecture:** Fill the existing `Publisher` seam with a `StocktwitsPublisher` that assembles a `multipart/form-data` body by hand and POSTs it with `urllib` (never `requests` — Stocktwits' Cloudflare blocks `requests`' TLS fingerprint). It writes the same `output/` artifacts as the dry-run publisher (after a successful post) so the nightly audit keeps passing. `run.py` selects the publisher from a new `--live` flag; the existing write-ahead state machine already gives the at-most-once guarantee that undeletable posts require.

**Tech Stack:** Python 3.12, stdlib only for the publisher (`urllib.request`, `json`), pytest. Tests MUST run via `.venv/bin/python -m pytest` (global python has an old yfinance without `yf.screen`).

## Global Constraints

- **Transport is `urllib`, never `requests`** in the Stocktwits publisher — CF blocks requests' TLS fingerprint (403); urllib passes, verified live incl. from Actions IPs.
- **Dry-run is the default.** Live posting happens only with `--live` AND `STOCKTWITS_ACCESS_TOKEN` set. `--live` with no token is a hard error, never a silent downgrade.
- **Copy is unchanged:** `compose_post_text` → `"$<st_symbol> printed a new 52-week high today"`. No price/%/mcap.
- **Cashtag symbology:** use `st_symbol()` (BRK-B → BRK.B) everywhere a symbol appears.
- **At-most-once:** a failed/blocked post must leave the ticker `pending` (blocked from re-selection, counts toward the daily cap) — lost, never duplicated.
- **Multipart chart field name is `chart`** (best-guess; the first live post confirms it) and is defined as a single module constant so a vendor correction is one line.
- **Config caps stay env-overridable with defaults `MAX_PER_TICK=2`, `MAX_PER_DAY=20`.** The launch ramp (`1`/`3`) is applied via environment variables, not by editing the defaults.
- **Secrets are never committed or pasted.** `STOCKTWITS_ACCESS_TOKEN` lives in the shell (local) and a GitHub Actions secret (CI).
- Run the whole suite with `.venv/bin/python -m pytest -q` and keep it green after every task.

---

### Task 1: Shared artifact writer + DryRunPublisher refactor

Extract the PNG/txt writing out of `DryRunPublisher` into a reusable helper so the live publisher can produce the identical audit artifacts without duplicated file logic.

**Files:**
- Create: `src/publish/record.py`
- Modify: `src/publish/dryrun.py`
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `write_post_artifacts(out_dir: Path, today: date, ticker: str, text: str, image_png: bytes) -> None` — writes `<out_dir>/<today ISO>/<ticker>.png` and `.txt` (UTF-8), creating the day dir. Used by Task 2.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_publish.py`:

```python
from datetime import date
from src.publish.record import write_post_artifacts

def test_write_post_artifacts_creates_png_and_txt(tmp_path):
    write_post_artifacts(tmp_path, date(2026, 7, 8), "AAPL",
                         "$AAPL printed a new 52-week high today", b"\x89PNGdata")
    day = tmp_path / "2026-07-08"
    assert (day / "AAPL.png").read_bytes() == b"\x89PNGdata"
    assert (day / "AAPL.txt").read_text(encoding="utf-8") == \
        "$AAPL printed a new 52-week high today"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_publish.py::test_write_post_artifacts_creates_png_and_txt -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.publish.record'`

- [ ] **Step 3: Create the helper**

Create `src/publish/record.py`:

```python
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
```

- [ ] **Step 4: Refactor DryRunPublisher to use it**

Replace the whole body of `src/publish/dryrun.py` with:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_publish.py -v`
Expected: PASS — the new test plus the existing `test_dryrun_writes_png_and_txt` (unchanged behavior).

- [ ] **Step 6: Commit**

```bash
git add src/publish/record.py src/publish/dryrun.py tests/test_publish.py
git commit -m "refactor: extract write_post_artifacts shared by publishers"
```

---

### Task 2: StocktwitsPublisher (multipart + urllib + response parse)

The core of the phase: a real publisher that POSTs the text + chart PNG to Stocktwits and writes the audit artifacts on success.

**Files:**
- Create: `src/publish/stocktwits_pub.py`
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `write_post_artifacts` (Task 1); `PostResult`, `Publisher` from `src.publish.base`; `Candidate` from `src.source.base`.
- Produces:
  - `class PublishError(Exception)` — raised on any non-success (HTTP error, CF block, error status in body, unparseable body). Consumed by Task 4's `run.py`.
  - `class StocktwitsPublisher(Publisher)` with
    `__init__(self, access_token: str, out_dir, today, *, user_agent=config.STOCKTWITS_USER_AGENT, url=config.STOCKTWITS_CREATE_URL, urlopen=urllib.request.urlopen, timeout: int = 15)`
    and `post(candidate, text, image_png) -> PostResult` returning `PostResult(post_id=str(id), dry_run=False)`.
  - Module constant `CHART_FIELD = "chart"` (the multipart file field name).

- [ ] **Step 1: Write the failing tests**

Add to the top of `tests/test_publish.py` (imports) and then the test bodies:

```python
import io
import json
import urllib.error
import pytest
from src.publish.stocktwits_pub import StocktwitsPublisher, PublishError
```

```python
class _FakeResp:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

def _pub(tmp_path, urlopen):
    return StocktwitsPublisher("TOKEN123", tmp_path, date(2026, 7, 8),
                               user_agent="ua/1.0",
                               url="https://st.example/create.json",
                               urlopen=urlopen)

def test_stocktwits_post_sends_multipart_and_returns_id(tmp_path):
    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        captured["data"] = req.data
        return _FakeResp(json.dumps(
            {"response": {"status": 200}, "message": {"id": 98765}}).encode())
    res = _pub(tmp_path, fake_urlopen).post(
        CAND, "$AAPL printed a new 52-week high today", b"\x89PNGdata")
    assert res == PostResult(post_id="98765", dry_run=False)
    body = captured["data"]
    assert b'name="access_token"' in body and b"TOKEN123" in body
    assert b'name="body"' in body and b"printed a new 52-week high" in body
    assert b'name="chart"; filename=' in body and b"\x89PNGdata" in body
    ct = captured["headers"]["content-type"]
    assert ct.startswith("multipart/form-data; boundary=")
    assert captured["headers"]["user-agent"] == "ua/1.0"

def test_stocktwits_post_writes_output_artifacts_on_success(tmp_path):
    def fake_urlopen(req, timeout=None):
        return _FakeResp(json.dumps(
            {"response": {"status": 200}, "message": {"id": 1}}).encode())
    _pub(tmp_path, fake_urlopen).post(
        CAND, "$AAPL printed a new 52-week high today", b"\x89PNGdata")
    day = tmp_path / "2026-07-08"
    assert (day / "AAPL.png").read_bytes() == b"\x89PNGdata"
    assert (day / "AAPL.txt").read_text(encoding="utf-8").startswith("$AAPL")

def test_stocktwits_post_raises_on_http_error(tmp_path):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            "https://st.example/create.json", 403, "Forbidden", {},
            io.BytesIO(b"blocked by cloudflare"))
    with pytest.raises(PublishError):
        _pub(tmp_path, fake_urlopen).post(CAND, "text", b"PNG")
    # a failed post writes NO artifact (ticker stays pending -> audit WARN, no orphan)
    assert not (tmp_path / "2026-07-08").exists()

def test_stocktwits_post_raises_on_error_status_in_body(tmp_path):
    def fake_urlopen(req, timeout=None):
        return _FakeResp(json.dumps(
            {"response": {"status": 400}, "errors": [{"message": "bad"}]}).encode())
    with pytest.raises(PublishError):
        _pub(tmp_path, fake_urlopen).post(CAND, "text", b"PNG")

def test_stocktwits_publisher_uses_urllib_not_requests():
    import inspect
    import src.publish.stocktwits_pub as m
    assert "import requests" not in inspect.getsource(m)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_publish.py -k stocktwits -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.publish.stocktwits_pub'`

- [ ] **Step 3: Implement the publisher**

Create `src/publish/stocktwits_pub.py`:

```python
"""Phase 2 publisher: posts text + chart PNG to Stocktwits' CORE messages/create.

urllib on purpose (see src/stocktwits.py): Stocktwits' Cloudflare blocks the
`requests` library's TLS fingerprint (403) but passes urllib. Multipart is
assembled by hand because urllib has no multipart helper.
"""
import json
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import config
from src.publish.base import Publisher, PostResult
from src.publish.record import write_post_artifacts
from src.source.base import Candidate

# The multipart file field for the chart image. Unconfirmed against current
# Stocktwits docs (offline); the first live post validates it. One line to fix.
CHART_FIELD = "chart"
_BOUNDARY = "----stocktwits52wkPosterBoundary7MA4YWxkTrZu0gW"


class PublishError(Exception):
    """A post did not succeed (HTTP error, CF block, error status, bad body).

    run.py catches this and leaves the ticker 'pending' (lost, never duplicated).
    """


def _encode_multipart(fields: dict[str, str],
                      file_field: str, filename: str, file_bytes: bytes,
                      content_type: str, boundary: str) -> bytes:
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    parts.append(f"--{boundary}\r\n".encode())
    parts.append((f'Content-Disposition: form-data; name="{file_field}"; '
                  f'filename="{filename}"\r\n').encode())
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


class StocktwitsPublisher(Publisher):
    def __init__(self, access_token: str, out_dir, today: date, *,
                 user_agent: str = config.STOCKTWITS_USER_AGENT,
                 url: str = config.STOCKTWITS_CREATE_URL,
                 urlopen=urllib.request.urlopen, timeout: int = 15):
        self.access_token = access_token
        self.out_dir = Path(out_dir)
        self.today = today
        self.user_agent = user_agent
        self.url = url
        self._urlopen = urlopen
        self.timeout = timeout

    def post(self, candidate: Candidate, text: str, image_png: bytes) -> PostResult:
        body = _encode_multipart(
            {"access_token": self.access_token, "body": text},
            CHART_FIELD, "chart.png", image_png, "image/png", _BOUNDARY)
        req = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"User-Agent": self.user_agent,
                     "Content-Type":
                         f"multipart/form-data; boundary={_BOUNDARY}"})
        try:
            with self._urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except (urllib.error.URLError, OSError) as e:  # HTTPError <: URLError
            raise PublishError(f"{candidate.ticker}: transport error: {e}") from e

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            raise PublishError(
                f"{candidate.ticker}: unparseable response: {raw[:200]!r}") from e
        status = (data.get("response") or {}).get("status")
        if status != 200:
            raise PublishError(
                f"{candidate.ticker}: stocktwits status {status}: {raw[:200]!r}")
        message_id = (data.get("message") or {}).get("id")
        if message_id is None:
            raise PublishError(
                f"{candidate.ticker}: no message id in response: {raw[:200]!r}")

        # Only after a confirmed post: write the auditable record.
        write_post_artifacts(self.out_dir, self.today, candidate.ticker,
                             text, image_png)
        return PostResult(post_id=str(message_id), dry_run=False)
```

- [ ] **Step 4: Add the config constants this imports (defer full config task to Task 3, but these two are needed now)**

In `config.py`, add near the other URLs (this is required for Task 2's import to resolve; Task 3 adds the ramp knobs):

```python
STOCKTWITS_CREATE_URL = "https://api.stocktwits.com/api/2/messages/create.json"
STOCKTWITS_USER_AGENT = "stocktwits-52wk-poster/1.0"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_publish.py -v`
Expected: PASS — all five new stocktwits tests plus Task 1's and the originals.

- [ ] **Step 6: Commit**

```bash
git add src/publish/stocktwits_pub.py tests/test_publish.py config.py
git commit -m "feat: StocktwitsPublisher posts text+chart via urllib multipart"
```

---

### Task 3: Env-overridable caps + config constants

Give the caps an environment override (defaults unchanged) so the launch ramp is a deploy-time setting, not a code edit.

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `config.MAX_PER_TICK` / `config.MAX_PER_DAY` read from env with defaults `2` / `20`. `STOCKTWITS_CREATE_URL`, `STOCKTWITS_USER_AGENT` (already added in Task 2 Step 4).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
import importlib

def test_caps_are_env_overridable(monkeypatch):
    monkeypatch.setenv("MAX_PER_TICK", "1")
    monkeypatch.setenv("MAX_PER_DAY", "3")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.MAX_PER_TICK == 1
        assert reloaded.MAX_PER_DAY == 3
    finally:
        monkeypatch.delenv("MAX_PER_TICK", raising=False)
        monkeypatch.delenv("MAX_PER_DAY", raising=False)
        importlib.reload(config)  # restore defaults for other tests

def test_stocktwits_constants_present():
    assert config.STOCKTWITS_CREATE_URL == \
        "https://api.stocktwits.com/api/2/messages/create.json"
    assert config.STOCKTWITS_USER_AGENT == "stocktwits-52wk-poster/1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_caps_are_env_overridable -v`
Expected: FAIL — `MAX_PER_TICK == 2` (env not yet honored), assertion error `2 != 1`.

- [ ] **Step 3: Make the caps env-overridable**

In `config.py`, add `import os` at the top (after `import re`), and replace the two cap lines:

```python
MAX_PER_TICK = int(os.environ.get("MAX_PER_TICK", "2"))   # posts per 30-min tick
MAX_PER_DAY = int(os.environ.get("MAX_PER_DAY", "20"))    # posts per trading day
```

Leave `MIN_MARKET_CAP`, `MAX_PLAUSIBLE_HIGHS`, and everything else unchanged. Confirm the two Stocktwits constants from Task 2 Step 4 are present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS — the new tests, and `test_caps_and_floors` still sees the `2`/`20` defaults (no env set).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: env-overridable MAX_PER_TICK/MAX_PER_DAY for launch ramp"
```

---

### Task 4: run.py `--live` wiring + PublishError handling

Select the real publisher behind `--live`, fail loudly if the token is missing, and skip (not crash) on an expected publish failure so one Cloudflare block doesn't forfeit a whole tick.

**Files:**
- Modify: `run.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `StocktwitsPublisher`, `PublishError` (Task 2); `DryRunPublisher` (Task 1).
- Produces: `build_publisher(live: bool, out_dir, today) -> Publisher` in `run.py`; `main()` gains a `--live` flag; `tick()` catches `PublishError` per post.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_run.py`:

```python
import os
from src.publish.dryrun import DryRunPublisher
from src.publish.stocktwits_pub import StocktwitsPublisher, PublishError

def test_build_publisher_dryrun_by_default(tmp_path):
    pub = run.build_publisher(False, tmp_path, TODAY)
    assert isinstance(pub, DryRunPublisher)

def test_build_publisher_live_needs_token(tmp_path, monkeypatch):
    monkeypatch.delenv("STOCKTWITS_ACCESS_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        run.build_publisher(True, tmp_path, TODAY)

def test_build_publisher_live_with_token(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKTWITS_ACCESS_TOKEN", "TKN")
    pub = run.build_publisher(True, tmp_path, TODAY)
    assert isinstance(pub, StocktwitsPublisher)

def test_publish_error_skips_ticker_and_continues(tmp_path):
    sp = tmp_path / "posted.json"
    class Flaky(Publisher):
        def post(self, candidate, text, image_png):
            if candidate.ticker == "BIG":
                raise PublishError("cloudflare 403")
            return PostResult(post_id="x", dry_run=False)
    got = run.tick(FakeSource([cand("BIG", 9e9), cand("MID", 5e9)]),
                   Flaky(), lambda c: b"PNG", sp, NOW)
    assert got == ["MID"]
    status = {e["ticker"]: e["status"] for e in state.load_posted(sp)}
    assert status == {"BIG": "pending", "MID": "posted"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_run.py -k "build_publisher or publish_error" -v`
Expected: FAIL — `AttributeError: module 'run' has no attribute 'build_publisher'`.

- [ ] **Step 3: Add `build_publisher` and the `--live` flag**

In `run.py`, update imports at the top to add:

```python
from src.publish.stocktwits_pub import PublishError, StocktwitsPublisher
```

Add this function above `main()`:

```python
def build_publisher(live: bool, out_dir: Path, today) -> Publisher:
    """Dry-run unless --live AND a token are present. --live without a token is
    a hard error, never a silent downgrade to dry-run."""
    if not live:
        return DryRunPublisher(out_dir, today)
    token = os.environ.get("STOCKTWITS_ACCESS_TOKEN", "")
    if not token:
        print("--live requires STOCKTWITS_ACCESS_TOKEN", file=sys.stderr)
        raise SystemExit(1)
    return StocktwitsPublisher(token, out_dir, today)
```

In `main()`, add the flag next to the others:

```python
    ap.add_argument("--live", action="store_true",
                    help="post to Stocktwits for real (needs STOCKTWITS_ACCESS_TOKEN)")
```

and replace the publisher line:

```python
    publisher = DryRunPublisher(args.output, today)  # Phase 2: swap for Stocktwits
```

with:

```python
    publisher = build_publisher(args.live, args.output, today)
```

- [ ] **Step 4: Catch PublishError in the posting loop**

In `run.py`'s `tick()`, replace the posting loop:

```python
    done: list[str] = []
    for c, png in ready:
        result = publisher.post(c, compose_post_text(c), png)
        state.mark_posted(state_path, c.ticker, today, result.post_id)
        done.append(c.ticker)
        print(f"posted {c.ticker} (dry_run={result.dry_run})")
    return done
```

with:

```python
    done: list[str] = []
    for c, png in ready:
        try:
            result = publisher.post(c, compose_post_text(c), png)
        except PublishError as e:
            # Expected failure (e.g. Cloudflare block): leave the ticker
            # 'pending' — blocked from re-selection today, lost, never duplicated.
            print(f"publish failed for {c.ticker}, staying pending: {e}",
                  file=sys.stderr)
            continue
        state.mark_posted(state_path, c.ticker, today, result.post_id)
        done.append(c.ticker)
        print(f"posted {c.ticker} (dry_run={result.dry_run})")
    return done
```

(Only `PublishError` is caught — an unexpected `RuntimeError` still crashes the tick loudly, as `test_publisher_crash_leaves_pending_writeahead` requires.)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — all tests, including the existing `test_publisher_crash_leaves_pending_writeahead` (RuntimeError still propagates) and the new `--live`/PublishError tests.

- [ ] **Step 6: Commit**

```bash
git add run.py tests/test_run.py
git commit -m "feat: --live flag selects StocktwitsPublisher; skip on PublishError"
```

---

### Task 5: Go-live rollout (manual — no automated test)

Approach A from the spec: one real post locally first, verify the chart attached, then flip Actions to live. These steps are operational and are performed by the human operator; they are **not** committed as part of the feature branch's code except the final `tick.yml` edit.

- [ ] **Step 1: Full green suite on the branch**

Run: `.venv/bin/python -m pytest -q` → all pass. Merge `feat/live-stocktwits-publisher` to `main` (publisher shipped, still dry-run everywhere — nothing posts yet).

- [ ] **Step 2: One real post, locally, from a residential IP**

With the market open, from the repo root on `main`:

```bash
export CHART_IMG_API_KEY=...        # existing chart key
export STOCKTWITS_ACCESS_TOKEN=...  # the real token (never commit/paste it)
MAX_PER_TICK=1 MAX_PER_DAY=3 .venv/bin/python run.py --live
```

Expected stdout: `... posting 1` then `posted <TICKER> (dry_run=False)`.

- [ ] **Step 3: Eyeball the live post**

Open the bot account's Stocktwits profile. Confirm on the newest post: (a) the **chart image actually attached** (not text-only), (b) the cashtag `$TICKER` links to the stream, (c) copy reads `printed a new 52-week high today`.

**Halt condition:** if the post is text-only, the `chart` multipart field is wrong — stop, ask Victor for the image-variant curl, correct `CHART_FIELD` in `src/publish/stocktwits_pub.py`, and repeat from Step 2 before automating.

- [ ] **Step 4: Commit the local state so Actions won't re-post the same ticker**

```bash
git add state/posted.json output
git commit -m "state: first live post <TICKER> $(date -u +'%Y-%m-%dT%H:%M')"
git push origin main
```

- [ ] **Step 5: Add the GitHub Actions secret**

Repo → Settings → Secrets and variables → Actions → New repository secret: `STOCKTWITS_ACCESS_TOKEN` = the token.

- [ ] **Step 6: Flip the tick workflow to live with the ramp**

Edit `.github/workflows/tick.yml` — in the "Run tick" step, add the token and ramp to `env:` and `--live` to the command:

```yaml
      - name: Run tick
        env:
          CHART_IMG_API_KEY: ${{ secrets.CHART_IMG_API_KEY }}
          STOCKTWITS_ACCESS_TOKEN: ${{ secrets.STOCKTWITS_ACCESS_TOKEN }}
          MAX_PER_TICK: "1"
          MAX_PER_DAY: "3"
          PYTHONUNBUFFERED: "1"
        run: python run.py --sync-state --live
```

Commit and push:

```bash
git add .github/workflows/tick.yml
git commit -m "ops: enable live Stocktwits posting (ramp 1/tick, 3/day)"
git push origin main
```

- [ ] **Step 7: Monitor the first automated ticks**

Watch the next few `tick` runs in the Actions tab for `posted … (dry_run=False)` and for any Cloudflare 403s in the logs. Confirm the nightly `audit` run is green. **Halt condition:** repeated CF blocks from Actions IPs → revisit fixed-IP egress (spec follow-up) before continuing.

---

## Follow-ups (recorded, not in this plan)

- After the first clean live week, remove the `MAX_PER_TICK`/`MAX_PER_DAY` env overrides from `tick.yml` to return to `2`/`20`.
- If Actions gets Cloudflare-blocked in practice, add fixed-IP egress for the POST.
- Replace `CHART_FIELD` with Victor's authoritative multipart field name if the first live post disproves `"chart"`.
