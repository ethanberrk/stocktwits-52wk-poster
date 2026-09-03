"""Thin Xignite client: token auth, 500-symbol batching, symbology, and the
three calls the poster needs (delayed quotes, market caps, daily history).

Xignite spells share classes with a dot (BRK.B); everything else in this
repo (state files, Stocktwits cashtags via st_symbol) uses the SEC/Yahoo dash
form (BRK-B). Callers pass dash-form tickers and get them back as keys.
"""
import urllib.parse
from datetime import date, datetime, timedelta

import config
from src.fetch import get_json
from src.source.base import SourceError


def xig_symbol(ticker: str) -> str:
    return ticker.replace("-", ".")


def parse_xig_date(s) -> date | None:
    """Xignite dates are M/D/YYYY on quotes, YYYY-MM-DD on history."""
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _token() -> str:
    if not config.XIGNITE_TOKEN:
        raise SourceError("DATA_SOURCE=xignite but XIGNITE_TOKEN is not set")
    return config.XIGNITE_TOKEN


def _get(url: str, params: dict):
    query = urllib.parse.urlencode({**params, "_token": _token()})
    return get_json(f"{url}?{query}")


def _check_batch(rows, what: str) -> list:
    """A batch where NOTHING succeeded is a broken feed (expired token, outage),
    not a quiet day — surface Xignite's own message and fail the tick red."""
    if not isinstance(rows, list) or not rows:
        raise SourceError(f"Xignite {what}: empty/invalid response")
    if all(r.get("Outcome") != "Success" for r in rows):
        raise SourceError(f"Xignite {what}: {rows[0].get('Outcome')}: "
                          f"{rows[0].get('Message')}")
    return rows


def quotes(tickers: list[str]) -> dict[str, dict]:
    """Delayed quotes keyed by the caller's (dash-form) ticker. Symbols Xignite
    can't match are simply absent."""
    out: dict[str, dict] = {}
    for i in range(0, len(tickers), config.XIGNITE_BATCH):
        chunk = tickers[i:i + config.XIGNITE_BATCH]
        rows = _check_batch(_get(config.XIGNITE_QUOTES_URL, {
            "IdentifierType": "Symbol",
            "Identifiers": ",".join(xig_symbol(t) for t in chunk),
        }), "quotes")
        by_sym = {r.get("Identifier"): r for r in rows}
        for t in chunk:
            r = by_sym.get(xig_symbol(t))
            if r and r.get("Outcome") == "Success":
                out[t] = r
    return out


_UNIT = {"Thousands": 1e3, "Millions": 1e6, "Billions": 1e9}


def market_caps(tickers: list[str]) -> dict[str, float]:
    """USD market cap per ticker (FactSet daily figure). Missing = absent."""
    out: dict[str, float] = {}
    for i in range(0, len(tickers), config.XIGNITE_BATCH):
        chunk = tickers[i:i + config.XIGNITE_BATCH]
        rows = _check_batch(_get(config.XIGNITE_FUNDAMENTALS_URL, {
            "IdentifierType": "Symbol",
            "Identifiers": ",".join(xig_symbol(t) for t in chunk),
            "FundamentalTypes": "MarketCapitalization",
            "AsOfDate": "", "ReportType": "Annual",
            "ExcludeRestated": "false", "UpdatedSince": "",
        }), "fundamentals")
        by_sym = {((r.get("Company") or {}).get("Symbol")): r for r in rows}
        for t in chunk:
            r = by_sym.get(xig_symbol(t))
            if not r or r.get("Outcome") != "Success":
                continue
            for fs in r.get("FundamentalsSets") or []:
                for f in fs.get("Fundamentals") or []:
                    if f.get("Type") == "MarketCapitalization" and f.get("Value"):
                        try:
                            out[t] = float(f["Value"]) * _UNIT.get(f.get("Unit"), 1.0)
                        except ValueError:
                            pass
    return out


def history(ticker: str, today: date) -> list[list]:
    """[[YYYY-MM-DD, o, h, l, c], ...] ascending, split-adjusted. Ends at the
    last COMPLETED session — Xignite's daily file does not carry today."""
    start = today - timedelta(days=config.XIGNITE_HISTORY_DAYS)
    d = _get(config.XIGNITE_HISTORY_URL, {
        "IdentifierType": "Symbol", "Identifier": xig_symbol(ticker),
        "StartDate": f"{start.month}/{start.day}/{start.year}",
        "EndDate": f"{today.month}/{today.day}/{today.year}",
        "AdjustmentMethod": "SplitOnly",
    })
    if not isinstance(d, dict) or d.get("Outcome") != "Success":
        raise SourceError(f"Xignite history {ticker}: "
                          f"{(d or {}).get('Outcome')}: {(d or {}).get('Message')}")
    rows = []
    for q in d.get("HistoricalQuotes") or []:
        if not q.get("Close"):
            continue
        dt = parse_xig_date(q.get("Date"))
        if dt is None:
            continue
        rows.append([dt.isoformat(), float(q["Open"]), float(q["High"]),
                     float(q["Low"]), float(q["Close"])])
    rows.sort(key=lambda r: r[0])
    return rows


def today_candle(quote: dict, today: date) -> list | None:
    """Today's [date, o, h, l, last] from a delayed quote, or None if the quote
    is stale (didn't trade today) or unusable."""
    if parse_xig_date(quote.get("Date")) != today:
        return None
    o, last = quote.get("Open"), quote.get("Last")
    if not o or not last:
        return None
    return [today.isoformat(), float(o), float(quote.get("High") or last),
            float(quote.get("Low") or last), float(last)]
