"""One tick: source -> validate -> pick -> verify symbol -> chart ->
write-ahead intent -> publish -> confirm."""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from src import select, state, stocktwits
from src.chart import ChartError, fetch_chart_png
from src.publish.base import Publisher, compose_post_text
from src.publish.dryrun import DryRunPublisher
from src.publish.stocktwits_pub import PublishError, StocktwitsPublisher
from src.source.base import HighsSource, SourceError
from src.source.yfinance_source import YFinanceSource

def tick(source: HighsSource, publisher: Publisher, chart_fetch,
         state_path: Path, now_utc: datetime, force: bool = False,
         symbol_check=lambda c: True, state_sync=None) -> list[str]:
    if not force and not state.is_market_hours(now_utc):
        print("outside market hours; nothing to do")
        return []
    today = now_utc.astimezone(ZoneInfo(config.MARKET_TZ)).date()

    candidates = source.fetch_candidates()
    select.validate(candidates)
    posted = state.load_posted(state_path)
    picks = select.pick(candidates, posted, today)
    print(f"{len(candidates)} on today's 52wk-high list; posting {len(picks)}")

    # Gather everything fallible BEFORE recording intent: a name that fails
    # its symbol check or chart fetch is skipped and stays eligible.
    ready = []
    for c in picks:
        if not symbol_check(c):
            print(f"stocktwits symbol check failed, skipping {c.ticker}")
            continue
        try:
            ready.append((c, chart_fetch(c)))
        except ChartError as e:
            print(f"chart failed, skipping {c.ticker}: {e}")
    if not ready:
        return []

    # Write-ahead: record intent, and push it (state_sync) before anything
    # irreversible happens. At-most-once: a crash or push race after this
    # point can only lose a post, never duplicate one.
    for c, _ in ready:
        state.append_posted(state_path, c.ticker, today, None, status="pending")
    if state_sync:
        state_sync()

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

def _git_sync_state() -> None:
    """Commit and push pending intents before posting. Any failure raises,
    aborting the tick BEFORE anything is posted — the safe side."""
    git = ["git", "-c", "user.name=52wk-poster-bot",
           "-c", "user.email=actions@users.noreply.github.com"]
    subprocess.run(git + ["add", "state"], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(git + ["commit", "-m", "state: pending post intents"], check=True)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)

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

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="run even outside market hours (local testing)")
    ap.add_argument("--sync-state", action="store_true",
                    help="git-push pending intents before posting (CI only)")
    ap.add_argument("--state", default="state/posted.json", type=Path)
    ap.add_argument("--output", default="output", type=Path)
    ap.add_argument("--live", action="store_true",
                    help="post to Stocktwits for real (needs STOCKTWITS_ACCESS_TOKEN)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(config.MARKET_TZ)).date()
    publisher = build_publisher(args.live, args.output, today)
    try:
        tick(YFinanceSource(), publisher,
             fetch_chart_png, args.state, now, args.force,
             symbol_check=stocktwits.symbol_exists,
             state_sync=_git_sync_state if args.sync_state else None)
    except (SourceError, select.ValidationError) as e:
        print(f"aborted: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
