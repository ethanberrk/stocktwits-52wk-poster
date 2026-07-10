# Self-Rendered Charts (drop chart-img API)

**Date:** 2026-07-10
**Status:** Approved pending user spec review
**Prior art:** `stocktwits-relative-strength-poster` `src/chart.py` + `src/fetch.py` (proven live in that repo's preview cron, keyless, works from GitHub Actions IPs)

## Goal

Replace the chart-img.com v2 API with an in-process matplotlib renderer ported
from the relative-strength poster. Kills the `CHART_IMG_API_KEY` dependency
(one of the two keys flagged for rotation), the paid plan, the rate limits,
and the "CHART-IMG.COM" watermark on every posted chart.

User approved the visual switch 2026-07-10 after a side-by-side of today's
five posted tickers (UNP, HSBC, MUFG, UBS, FTNT) — all five rendered
successfully, including the foreign-bank ADRs.

## Approach (chosen: straight port)

Copy the proven module rather than extract a shared library (two tiny repos,
packaging overhead not justified) or keep chart-img as fallback (keeps the key
alive, defeats the purpose). Duplicated-module-per-repo is the pattern these
repos already follow (`stocktwits.py` urllib client).

## Changes

### `src/chart.py` — replaced wholesale
Port the RS poster's version. Pipeline: fetch 1Y daily OHLC from
stockanalysis.com (keyless JSON) → append today's candle from the live quote
(the daily-history endpoint lags one session) → draw TradingView-light-style
candlestick PNG (up `#089981` / down `#F23645`, recessive grid, month
boundaries, right-hand price axis, dashed last-price line + pill, top-left
`EXCHANGE:TICKER` + OHLC legend) at 800×450, matching the current chart size.

Adaptations from the RS original:
- Signature becomes `fetch_chart_png(candidate)` — **no `api_key` param**.
- `Candidate` import points at this repo's dataclass (chart code only uses
  `.ticker` and `.exchange`; both repos have those fields).
- `ChartError` semantics unchanged: any data/render failure raises it, the
  tick loop skips that ticker, it stays eligible. Failure mode is a missing
  post, never a bad one.

The pre-market artifact that motivated pinning chart-img to
`session="regular"` (PR #1) cannot recur by construction: daily history has no
extended-hours bars, and the appended candle comes from the live quote during
market hours (ticks only run 9:30–16:00 ET).

### `src/fetch.py` — new, copied verbatim
`get_json(url)`: urllib (not requests — consistent with the repo's
CDN-fingerprint stance), browser UA, 4 tries with backoff on 429/503,
returns `None` on failure.

### `config.py`
- Remove `CHART_IMG_URL`.
- Add `SA_HISTORY_URL`, `SA_QUOTE_URL` (stockanalysis.com endpoints, values
  copied from the RS repo), `MIN_HISTORY_DAYS = 330`, `CHART_WIDTH = 800`,
  `CHART_HEIGHT = 450`.

### `run.py`
Remove the `CHART_IMG_API_KEY` presence check and the
`lambda c: fetch_chart_png(c, api_key)` wrapper; pass `fetch_chart_png`
directly. No other tick-loop changes.

### `.github/workflows/tick.yml`
Remove the `CHART_IMG_API_KEY` env line. (Audit workflow doesn't use it.)

### `requirements.txt`
Add `matplotlib>=3.8`; remove `requests>=2.31` (chart.py was the only direct
user; yfinance declares its own requests dependency). Install matplotlib into
`.venv` locally.

### Tests
- Replace `tests/test_chart.py` with the RS repo's 10-test suite (fixture
  history → render assertions, ChartError paths, IPO cutoff, today's-candle
  append), adjusted for this repo's `Candidate`.
- Delete `tests/contract/test_live_chart_img.py`; add
  `tests/contract/test_live_chart_render.py`: live stockanalysis history fetch
  for a stable mega-cap + full render, assert PNG magic and >10 KB.
- `scripts/verify_day.py` needs no change — its artifact checks (PNG magic,
  ≥10 KB size floor) are renderer-agnostic; self-rendered PNGs run 25–31 KB.
- `tests/test_publish.py`'s no-requests-in-publisher assertion is unaffected.

## Deliberate behavior changes

1. **Chart look changes** on the live account (approved via side-by-side):
   watermark gone, `EXCHANGE:TICKER` legend instead of full company name,
   dashed last-price line (sits at the chart top on a 52wk-high post).
2. **Recent IPOs get skipped**: `MIN_HISTORY_DAYS = 330` — if history doesn't
   reach back ~11 months, `ChartError` (a "1Y" chart of 3 months of data
   misleads). New filter this repo didn't have; aligns with the IPO filter the
   user requested on the RS poster 2026-07-10 morning.
3. **New external dependency**: stockanalysis.com (unofficial, keyless)
   replaces chart-img (official, paid). Already relied on by the RS poster;
   failure fails safe (skip ticker, retry next tick).

## Rollout

1. Build on a branch, full suite green via `.venv/bin/python -m pytest`.
2. Local dry-run tick; eyeball the produced `output/` PNGs.
3. Merge. Dry-run and live share the chart path, so next trading day's posts
   use self-rendered charts automatically. No posting ramp needed (chart
   failure = skip, never a malformed post).
4. Post-merge cleanup: delete the `CHART_IMG_API_KEY` GitHub secret; user can
   cancel the chart-img plan. Drops one of the two flagged key rotations
   (Stocktwits token rotation still open).

## Out of scope (deferred)

- Company name in the chart legend (Candidate has `.name`; add later if asked).
- Volume pane, dark-theme charts, any styling divergence from the RS renderer.
- The dead-man's-switch / spacing-guard hardening items from 2026-07-09 —
  unrelated to charts, still the obvious next hardening.
- **Tick starvation on deterministic ChartErrors (final-review finding,
  deferred 2026-07-10):** `select.pick` takes the top-N by market cap and a
  chart-failed ticker stays eligible, so a name that fails *permanently*
  (e.g. a recent mega-IPO tripping the MIN_HISTORY_DAYS guard) is re-picked
  every tick and can silence the bot for the day under MAX_PER_TICK=1. Fix
  direction: have the tick walk further down the eligible list until it
  fills MAX_PER_TICK ready names. Ranks with the dead-man's-switch as top
  hardening work.
