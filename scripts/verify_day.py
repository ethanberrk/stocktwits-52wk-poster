#!/usr/bin/env python3
"""Independent auditor: re-derives ground truth and checks every claim the
pipeline made. This is deliberately a DIFFERENT data path than the poster
(per-ticker daily history, not the screener), so it is not the pipeline
grading its own homework.

Checks
  truth      each posted ticker really printed a 52-week high that day
             (day high >= max High of up to 252 prior sessions, 0.1% tol)
  rules      replayed over the whole posted log + git history:
             no duplicate (ticker, day); no consecutive-trading-day repost;
             <= MAX_PER_DAY per day; <= MAX_PER_TICK added per tick commit;
             no weekend posts
  artifacts  output/<day>/<TICKER>.png is a real PNG; .txt starts with the
             cashtag and mentions the 52-week high; state and files agree

Usage
  python scripts/verify_day.py 2026-07-02 [...]   audit specific day(s)
  python scripts/verify_day.py --all              every day in the log
  python scripts/verify_day.py --today            today (ET); used by CI
Exits nonzero if any check FAILs (WARNs do not fail the run).
"""
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config                      # noqa: E402
from src import state              # noqa: E402
from src.stocktwits import st_symbol  # noqa: E402

TRUTH_TOLERANCE = 0.001            # 0.1%: feed rounding between Yahoo endpoints
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

results = {"PASS": 0, "WARN": 0, "FAIL": 0}

def report(level: str, check: str, detail: str) -> None:
    results[level] += 1
    print(f"{level:4} [{check}] {detail}")

# ---------------------------------------------------------------- rules ----

def check_log_rules(posted: list[dict]) -> None:
    """Global invariants over the full posted log (pure; unit-tested)."""
    fails_before = results["FAIL"]
    seen: set[tuple[str, str]] = set()
    by_day: dict[str, int] = {}
    for e in posted:
        key = (e["ticker"], e["date"])
        if key in seen:
            report("FAIL", "rules", f"duplicate post {e['ticker']} on {e['date']}")
        seen.add(key)
        by_day[e["date"]] = by_day.get(e["date"], 0) + 1

        d = date.fromisoformat(e["date"])
        if d.weekday() >= 5:
            report("FAIL", "rules", f"{e['ticker']} posted on a weekend ({d})")
        prev = state.previous_trading_day(d)
        if (e["ticker"], prev.isoformat()) in seen:
            report("FAIL", "rules",
                   f"cooldown violation: {e['ticker']} on {prev} and again {d}")

    for day, n in by_day.items():
        if n > config.MAX_PER_DAY:
            report("FAIL", "rules", f"{n} posts on {day} > daily cap {config.MAX_PER_DAY}")
    if results["FAIL"] == fails_before:
        report("PASS", "rules",
               f"log invariants over {len(posted)} posts / {len(by_day)} day(s) "
               "(duplicates, cooldown, weekend, daily cap)")

def check_per_tick_batches() -> None:
    """Each git commit touching the posted log may add at most MAX_PER_TICK."""
    shas = subprocess.run(
        ["git", "log", "--reverse", "--format=%H", "--", "state/posted.json"],
        capture_output=True, text=True, cwd=ROOT, check=True).stdout.split()
    prev_n = 0
    ok = True
    for sha in shas:
        try:
            blob = subprocess.run(["git", "show", f"{sha}:state/posted.json"],
                                  capture_output=True, text=True, cwd=ROOT,
                                  check=True).stdout
        except subprocess.CalledProcessError:
            continue                     # file absent at this commit
        posts = json.loads(blob)["posts"]
        added = posts[prev_n:]
        if len(added) > config.MAX_PER_TICK:
            ok = False
            report("FAIL", "rules",
                   f"commit {sha[:7]} added {len(added)} posts > per-tick cap "
                   f"{config.MAX_PER_TICK}: {[e['ticker'] for e in added]}")
        if len({e['date'] for e in added}) > 1:
            ok = False
            report("FAIL", "rules", f"commit {sha[:7]} mixes dates: {added}")
        prev_n = len(posts)
    if ok:
        report("PASS", "rules", f"per-tick additions <= {config.MAX_PER_TICK} "
               f"across {len(shas)} state commit(s)")

# ---------------------------------------------------------------- truth ----

def check_truth(ticker: str, d: date) -> None:
    import yfinance as yf              # imported here: rules/artifacts stay offline
    df = yf.Ticker(ticker).history(start=d - timedelta(days=550),
                                   end=d + timedelta(days=1), auto_adjust=False)
    if df.empty:
        report("FAIL", "truth", f"{ticker}: no history returned")
        return
    days = [ts.date() for ts in df.index]
    if d not in days:
        report("FAIL", "truth", f"{ticker}: did not trade on {d}")
        return
    i = days.index(d)
    prior = df["High"].iloc[max(0, i - 252):i]
    if prior.empty:
        report("WARN", "truth", f"{ticker}: no prior sessions (IPO day?); skipping")
        return
    prior_max, day_high = float(prior.max()), float(df["High"].iloc[i])
    margin = (day_high - prior_max) / prior_max
    detail = (f"{ticker} {d}: day high {day_high:.2f} vs prior-252-session max "
              f"{prior_max:.2f} ({margin:+.2%})")
    if day_high >= prior_max * (1 - TRUTH_TOLERANCE):
        level = "PASS" if len(prior) >= 200 else "WARN"
        suffix = "" if len(prior) >= 200 else f" [only {len(prior)} prior sessions]"
        report(level, "truth", detail + suffix)
    else:
        report("FAIL", "truth", detail + " — NOT a 52-week high")

# ------------------------------------------------------------- artifacts ----

def check_artifacts(posted: list[dict], d: date) -> None:
    day_dir = ROOT / "output" / d.isoformat()
    entries = [e for e in posted if e["date"] == d.isoformat()]
    files = {p.name for p in day_dir.iterdir()} if day_dir.is_dir() else set()
    files.discard(".gitkeep")
    for e in entries:
        t = e["ticker"]
        if e.get("status", "posted") == "pending":
            report("WARN", "artifacts",
                   f"{t} {d}: write-ahead entry never confirmed (crash between "
                   "intent and post?) — verify manually whether it went out")
            files.discard(f"{t}.png"); files.discard(f"{t}.txt")
            continue
        png, txt = day_dir / f"{t}.png", day_dir / f"{t}.txt"
        if not png.is_file() or png.read_bytes()[:8] != PNG_MAGIC:
            report("FAIL", "artifacts", f"{t} {d}: missing/invalid PNG")
        elif png.stat().st_size < 10_000:
            report("WARN", "artifacts", f"{t} {d}: PNG suspiciously small "
                   f"({png.stat().st_size} bytes)")
        else:
            report("PASS", "artifacts", f"{t} {d}: valid PNG "
                   f"({png.stat().st_size:,} bytes)")
        if not txt.is_file():
            report("FAIL", "artifacts", f"{t} {d}: missing .txt")
        else:
            text = txt.read_text(encoding="utf-8")
            if text.startswith(f"${st_symbol(t)} ") and "52-week high" in text:
                report("PASS", "artifacts", f"{t} {d}: copy ok: {text!r}")
            else:
                report("FAIL", "artifacts", f"{t} {d}: unexpected copy: {text!r}")
        files.discard(f"{t}.png"); files.discard(f"{t}.txt")
    if files:
        report("FAIL", "artifacts", f"{d}: orphan files with no state entry: {sorted(files)}")
    if not entries:
        report("PASS", "artifacts", f"{d}: no posts recorded"
               + (" and no stray files" if not files else ""))

# ----------------------------------------------------------------- main ----

def main(argv: list[str]) -> int:
    posted = state.load_posted(ROOT / "state" / "posted.json")
    all_days = sorted({e["date"] for e in posted})

    if "--all" in argv:
        days = [date.fromisoformat(x) for x in all_days]
    elif "--today" in argv:
        days = [datetime.now(ZoneInfo(config.MARKET_TZ)).date()]
    else:
        days = [date.fromisoformat(x) for x in argv[1:]]
    if not days and not posted:
        print("posted log is empty; nothing to audit")
        return 0

    print(f"auditing day(s): {', '.join(str(d) for d in days)}"
          f" | posted log: {len(posted)} entries across {len(all_days)} day(s)\n")
    check_log_rules(posted)
    check_per_tick_batches()
    for d in days:
        check_artifacts(posted, d)
    for d in days:
        for e in (x for x in posted if x["date"] == d.isoformat()):
            check_truth(e["ticker"], d)

    print(f"\nsummary: {results['PASS']} pass, {results['WARN']} warn, "
          f"{results['FAIL']} fail")
    return 1 if results["FAIL"] else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
