"""Shadow comparison for the data-source switch.

Runs the data source that is NOT active, diffs it against the candidate list
the live tick just dumped (shadow/<date>/<HHMM>.active.json), replays the
selection rules on both, and writes shadow/<date>/<HHMM>.json. Never touches
state/ or posts anything. Usage: python scripts/shadow.py [--force]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config                                  # noqa: E402
from run import build_source                   # noqa: E402
from src import select, state                  # noqa: E402
from src.source.base import Candidate          # noqa: E402


def other(name: str) -> str:
    return "xignite" if name == "legacy" else "legacy"


def load_active_dump(day_dir: Path) -> tuple[Path | None, dict | None]:
    dumps = sorted(day_dir.glob("*.active.json"))
    if not dumps:
        return None, None
    return dumps[-1], json.loads(dumps[-1].read_text())


def compare(active: str, active_cands: list[Candidate], shadow: str,
            shadow_cands: list[Candidate], posted: list[dict], today) -> dict:
    a = {c.ticker for c in active_cands}
    s = {c.ticker for c in shadow_cands}
    picks = {active: [c.ticker for c in select.pick(active_cands, posted, today)],
             shadow: [c.ticker for c in select.pick(shadow_cands, posted, today)]}
    return {
        "active": active, "shadow": shadow,
        "counts": {"active": len(a), "shadow": len(s), "both": len(a & s)},
        "only_in_active": sorted(a - s),
        "only_in_shadow": sorted(s - a),
        "would_pick": picks,
        "picks_agree": picks[active] == picks[shadow],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="run outside market hours")
    ap.add_argument("--state", default="state/posted.json", type=Path)
    ap.add_argument("--shadow-dir", default=config.SHADOW_DIR, type=Path)
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    if not args.force and not state.is_market_hours(now):
        print("outside market hours; no shadow run")
        return 0
    today = now.astimezone(ZoneInfo(config.MARKET_TZ)).date()
    day_dir = args.shadow_dir / today.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)

    active = config.DATA_SOURCE
    shadow = other(active)
    dump_path, dump = load_active_dump(day_dir)
    stamp = dump_path.name.split(".")[0] if dump_path else now.strftime("%H%M")
    out_path = day_dir / f"{stamp}.json"
    result = {"time": now.isoformat(timespec="seconds"), "active": active, "shadow": shadow}

    try:
        shadow_cands = build_source(shadow).fetch_candidates()
    except Exception as e:                       # shadow must never break the tick
        result["error"] = f"{shadow} source failed: {e}"
        out_path.write_text(json.dumps(result, indent=1))
        print(result["error"], file=sys.stderr)
        return 1

    if dump is None:
        result["error"] = "no active candidate dump this tick (tick aborted early?)"
        result["counts"] = {"shadow": len(shadow_cands)}
        result["shadow_top"] = [c.ticker for c in
                                sorted(shadow_cands, key=lambda c: -c.market_cap)[:5]]
    else:
        active_cands = [Candidate(**c) for c in dump["candidates"]]
        posted = state.load_posted(args.state) if args.state.exists() else []
        result.update(compare(active, active_cands, shadow, shadow_cands, posted, today))
        dump_path.unlink()                       # the diff supersedes the raw dump
    out_path.write_text(json.dumps(result, indent=1))
    c = result.get("counts", {})
    print(f"shadow {shadow} vs active {active}: {c} "
          f"picks_agree={result.get('picks_agree')} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
