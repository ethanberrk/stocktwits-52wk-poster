"""Print a day's shadow comparisons. Usage: python scripts/shadow_report.py [YYYY-MM-DD]"""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    day = argv[0] if argv else datetime.now(ZoneInfo(config.MARKET_TZ)).date().isoformat()
    files = sorted((Path(config.SHADOW_DIR) / day).glob("[0-9][0-9][0-9][0-9].json"))
    if not files:
        print(f"no shadow files for {day}")
        return 1
    agree = total = 0
    print(f"{'tick':>5} {'active':>7} {'shadow':>7} {'both':>5}  only-active | only-shadow | picks")
    for f in files:
        r = json.loads(f.read_text())
        if "error" in r:
            print(f"{f.stem:>5}  ERROR {r['error']}")
            continue
        c = r["counts"]
        total += 1
        agree += bool(r["picks_agree"])
        wp = r["would_pick"]
        print(f"{f.stem:>5} {c['active']:>7} {c['shadow']:>7} {c['both']:>5}  "
              f"{','.join(r['only_in_active']) or '-'} | "
              f"{','.join(r['only_in_shadow']) or '-'} | "
              f"{'SAME' if r['picks_agree'] else 'DIFF'} "
              f"{wp[r['active']]} vs {wp[r['shadow']]}")
    if total:
        print(f"\n{day}: picks agreed on {agree}/{total} ticks "
              f"(active={r['active']}, shadow={r['shadow']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
