"""All knobs in one place. Nothing else defines numbers or thresholds."""
import os
import re

MIN_MARKET_CAP = 1_000_000_000          # USD floor
MAX_PER_TICK = int(os.environ.get("MAX_PER_TICK", "2"))   # posts per 30-min tick
MAX_PER_DAY = int(os.environ.get("MAX_PER_DAY", "20"))    # posts per trading day
MAX_PLAUSIBLE_HIGHS = 500               # validation gate: more = broken source

MARKET_TZ = "America/New_York"
MARKET_OPEN = (9, 30)                   # ET
MARKET_CLOSE = (16, 0)                  # ET

# Self-rendered charts: keyless daily-OHLC history + live quote from
# stockanalysis.com (same source the relative-strength poster runs on).
SA_QUOTE_URL = "https://stockanalysis.com/api/quotes/s/{ticker}"
SA_HISTORY_URL = ("https://stockanalysis.com/api/symbol/s/{ticker}/history"
                  "?range=1Y&period=Daily")
MIN_HISTORY_DAYS = 330      # refuse a "1Y" chart for a recent IPO with less
                            # than ~11 months of candles — it would mislead
CHART_WIDTH = 800           # px; matches the size chart-img produced
CHART_HEIGHT = 450
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
