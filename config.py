"""All knobs in one place. Nothing else defines numbers or thresholds."""
import re

MIN_MARKET_CAP = 1_000_000_000          # USD floor
MAX_PER_TICK = 2                        # posts per 30-min tick
MAX_PER_DAY = 20                        # posts per trading day
MAX_PLAUSIBLE_HIGHS = 500               # validation gate: more = broken source

MARKET_TZ = "America/New_York"
MARKET_OPEN = (9, 30)                   # ET
MARKET_CLOSE = (16, 0)                  # ET

# v2 (POST + JSON body): the only version exposing `session`, which we pin to
# "regular" so a chart captured at the open never shows a pre-market price line.
CHART_IMG_URL = "https://api.chart-img.com/v2/tradingview/advanced-chart"
# public, unauthenticated; used to validate a cashtag resolves before posting
STOCKTWITS_SYMBOL_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
STOCKTWITS_CREATE_URL = "https://api.stocktwits.com/api/2/messages/create.json"
STOCKTWITS_USER_AGENT = "stocktwits-52wk-poster/1.0"

# Drop non-common-equity by name (same rule the WSJ prototype proved out)
NAME_EXCLUDE_RE = re.compile(
    r"\b(ETF|Fund|Pfd|Preferred|Notes?|Units?|Warrants?|Wt|Bond|Rt|Rights)\b"
    r"|Acquisition Corp",
    re.I,
)
