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
