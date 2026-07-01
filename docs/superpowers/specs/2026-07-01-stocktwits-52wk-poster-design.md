# Stocktwits 52-Week-High Poster — Design Spec

**Date:** 2026-07-01
**Status:** Approved design, pre-implementation
**Repo:** `stocktwits-52wk-poster` (new, from scratch — deliberately independent of the `stocktwits-relative-strength` prototype)

## Purpose

An automated account posts timely, curated 52-week-high calls to Stocktwits throughout the trading day: when a US stock hits a new 52-week high intraday, the system posts a 1-year chart image with a `$TICKER` cashtag and a short blurb. Posts trickle out as highs occur (never a batch dump), capped per day, and never repost the same name on consecutive trading days.

## Decisions made (and why)

| Decision | Choice | Rationale |
| --- | --- | --- |
| Relationship to prototype | From scratch | Prototype's WSJ/Yahoo endpoints are unofficial and explicitly flagged as not long-lived |
| Data source | yfinance first, FMP Starter (~$22/mo) later | $0 to start with the least code (Yahoo screener + `fiftyTwoWeekHigh` on quotes); source is one swappable module. FMP is the researched upgrade: real screener + `yearHigh` in every quote, ~3 endpoints, stateless |
| Chart images | Chart API service (chart-img.com, TradingView-rendered) | Polished charts for zero rendering code; also means the data provider never supplies chart data — cleaner licensing story |
| Post shape | One post per stock: chart PNG + `$TICKER` + templated blurb | Cashtags land posts in each ticker's stream |
| Timing | Live intraday — detect and post as highs happen | Timely ("just hit a new 52-week high") beats end-of-day recaps; trickle emerges naturally |
| Selection ranking | Largest market cap first | Starting default; the select layer is built to be swapped/refined |
| Hosting | GitHub Actions scheduled workflow | Free, zero infra, secrets + failure emails built in; proven by the prototype |
| Interim posting | Minimal dry-run writer only | Stocktwits API access arrives within days — no workaround gets built |

## Architecture

One Python package. One GitHub Actions workflow ("tick") runs **every 30 minutes during market hours**, weekdays ~9:45am–4:00pm ET. Cron is expressed in UTC with a wide window; each run gates itself in code against `America/New_York` so DST never misfires. Runs are short-lived and stateless except two small JSON state files committed back to the repo.

### Per-tick data flow

1. **Source** — fetch US equities currently at new 52-week highs (today's high ≥ trailing 52-week high) via the `HighsSource` interface. v1: yfinance.
2. **Select** — filter: common stock only (no ETFs/funds/preferreds/units), market cap > $1B, not blocked by the cooldown rule. Rank survivors by market cap descending.
3. **Throttle** — post at most **2 per tick** and **20 per day** (config). 13 ticks × 2 = 26 slots, so the daily cap binds on heavy days; the trickle is structural.
4. **Chart** — fetch a 1-year chart PNG for each winner from chart-img.
5. **Publish** — compose text (`$TICKER` + new-52wk-high blurb with price and % move) and hand to the `Publisher`. Phase 1: dry-run writer to `output/YYYY-MM-DD/`. Phase 2: Stocktwits API client.
6. **Record** — append ticker/timestamp/post-id to `state/posted.json`, bump `state/daily_count.json`, commit and push both.

A tick that finds nothing new and qualifying exits cleanly — most ticks will.

### Cooldown rule (exact semantics)

A ticker is **skipped** if it was already posted **today or on the immediately preceding trading day**. It is **eligible again** after one full trading day's gap: posted Monday → blocked Tuesday → new high Wednesday → posts Wednesday. Weekends/holidays don't count as gap days (posted Friday → blocked Monday → eligible Tuesday). Trading-day math lives in `state.py`.

### Repo layout

```
stocktwits-52wk-poster/
├── run.py                  # entrypoint: one tick per invocation
├── config.py               # all knobs: caps, $1B threshold, market-hours window, cooldown
├── src/
│   ├── source/
│   │   ├── base.py         # HighsSource: fetch_candidates() -> list[Candidate]
│   │   └── yfinance_source.py
│   ├── select.py           # filters + cooldown + mcap ranking + caps
│   ├── chart.py            # chart-img client -> 1yr PNG bytes
│   ├── publish/
│   │   ├── base.py         # Publisher: post(ticker, text, image) -> PostResult
│   │   ├── dryrun.py       # output/YYYY-MM-DD/<ticker>.png + .txt
│   │   └── stocktwits.py   # Phase 2
│   └── state.py            # posted-log, daily count, trading-day math
├── state/posted.json
├── output/                 # dry-run artifacts (gitignored or committed — TBD at impl)
├── tests/
└── .github/workflows/tick.yml
```

**`Candidate`** — one dataclass: `ticker, name, price, pct_change_today, market_cap, week52_high, security_type`. It is the only contract between source and downstream; nothing else imports yfinance.

### Config defaults

| Knob | Default |
| --- | --- |
| Max posts per tick | 2 |
| Max posts per day | 20 |
| Min market cap | $1B |
| Cooldown | No repost on consecutive trading days |
| Tick cadence | Every 30 min, ~9:45am–4:00pm ET, weekdays |

## Error handling

- **Source failure / rate limit** (yfinance's known mode): log, exit nonzero → GitHub emails on workflow failure. A missed tick is harmless; still-standing highs surface next tick.
- **Chart failure for one ticker:** skip it this tick (stays eligible), continue down the ranked list.
- **Post succeeded, state-push failed** — the one double-post risk. Write state before pushing; pull-rebase-push; the consecutive-day rule catches most residual dupes.
- **Validation gate before any posting:** abort the tick if source output looks broken (empty fields across the board, implausible count like thousands of "highs").

## Testing

- **Unit tests (CI):** fixture-driven tests for select/cooldown/caps/ranking and post-text templating. Must cover: Mon-post → Wed-eligible; Fri-post → Mon-blocked → Tue-eligible; per-tick and daily caps interacting; ETF/preferred exclusion.
- **Contract tests (manual-only):** thin live checks of yfinance and chart-img shapes, excluded from CI.
- **End-to-end:** `--dry-run` flag runnable locally on any market day.

## Build phases

**Phase 1 (now):** full pipeline with dry-run publisher, on schedule, producing daily `output/` folders for eyeballing.

**Phase 2 (when API access lands, ~days):** implement `publish/stocktwits.py` against the real API, add secrets to Actions, flip config. Refine post copy against real rendering.

## Deferred backlog (tracked here + ROADMAP when repo matures)

- **FMP source swap** — move off yfinance when it breaks or the project proves out; FMP Starter ~$22/mo, endpoints already researched (screener + batch quotes with `yearHigh`).
- **Smarter selection** — replace largest-market-cap with a refined heuristic (candidates discussed: fewest Stocktwits watchers "relative strength" thesis, % gain, engagement-informed).
- **Market-holiday calendar** — v1 relies on "no new data on holidays" + cooldown; a proper exchange calendar (e.g. `pandas-market-calendars`) is cleaner.
- **Data-display licensing** — all individual-tier data providers formally restrict public display; chart-img shifts chart licensing to the chart service. Revisit if the account becomes commercial (FMP sells display licensing as an upgrade).
- **Engagement feedback loop** — use Stocktwits post metrics to tune selection.

## Open questions (non-blocking)

- chart-img.com account/tier and exact chart styling — pick during Phase 1 implementation.
- Stocktwits posting API contract (auth, image upload, rate limits) — unknown until access arrives; `Publisher` interface isolates it.
- Whether `output/` dry-run artifacts get committed or stay local/Actions-artifacts — decide at implementation.
