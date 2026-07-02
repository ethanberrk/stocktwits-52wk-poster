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
