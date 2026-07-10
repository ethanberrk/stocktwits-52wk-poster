"""Self-rendered 1-year daily candlestick chart (matplotlib -> PNG bytes).

Replaces the chart-img API: history comes keyless from stockanalysis.com and
the chart is drawn in-process in the TradingView light style (up #089981,
down #F23645, recessive grid, right-hand price axis, last-price pill). The
daily history endpoint lags one session, so today's candle is appended from
the live quote — a 52wk-high post whose chart stopped yesterday would be
missing its own move.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import io

from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle

import config
from src.fetch import get_json
from src.source.base import Candidate
from src.stocktwits import st_symbol

UP, DOWN = "#089981", "#F23645"
INK, MUTED, GRID = "#131722", "#787b86", "#e9edf1"
_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class ChartError(Exception):
    """Chart data/render failed for this ticker; skip it this tick (stays eligible)."""


def _fetch_history(ticker: str, today: date | None = None) -> list[list]:
    """[[YYYY-MM-DD, o, h, l, c], ...] ascending, ending with today's candle."""
    if today is None:
        today = datetime.now(ZoneInfo(config.MARKET_TZ)).date()
    sa_symbol = st_symbol(ticker)
    d = get_json(config.SA_HISTORY_URL.format(ticker=sa_symbol))
    rows = (d or {}).get("data") or []
    hist = sorted(([r["t"], r["o"], r["h"], r["l"], r["c"]] for r in rows),
                  key=lambda r: r[0])
    if not hist:
        raise ChartError(f"{ticker}: no daily history from stockanalysis")
    cutoff = (today - timedelta(days=config.MIN_HISTORY_DAYS)).isoformat()
    if hist[0][0] > cutoff:
        raise ChartError(
            f"{ticker}: history starts {hist[0][0]}, needs to reach back to "
            f"{cutoff} — likely a recent IPO, 1Y chart would mislead")
    if hist[-1][0] < today.isoformat():
        q = (get_json(config.SA_QUOTE_URL.format(ticker=sa_symbol)) or {}).get("data")
        if q and q.get("p") and q.get("o"):
            p = float(q["p"])
            hist.append([today.isoformat(), float(q["o"]),
                         float(q.get("h") or p), float(q.get("l") or p), p])
        else:
            raise ChartError(
                f"{ticker}: history ends {hist[-1][0]}, live quote unusable "
                f"— chart would miss today's move")
    return hist


def _legend_text(hist: list[list]) -> str:
    """TradingView-style OHLC line; change is vs the PREVIOUS close (falls
    back to today's open on the first candle), matching how TradingView and
    quote pages report the day's move on gap days."""
    o, hi_d, lo_d, c = hist[-1][1:]
    base = hist[-2][4] if len(hist) > 1 else o
    chg = c - base
    return (f"1D · 1Y · O {o:,.2f}  H {hi_d:,.2f}  L {lo_d:,.2f}  C {c:,.2f}"
            f"  {chg:+,.2f} ({chg / base * 100:+.2f}%)")


def _render_png(candidate: Candidate, hist: list[list]) -> bytes:
    w, h = config.CHART_WIDTH / 100, config.CHART_HEIGHT / 100
    fig, ax = plt.subplots(figsize=(w, h), dpi=100)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(left=0.012, right=0.925, top=0.90, bottom=0.075)

    n = len(hist)
    body_w = 0.7  # in index units; thin at 1Y density
    for i, (_, o, hi, lo, c) in enumerate(hist):
        col = UP if c >= o else DOWN
        ax.plot([i, i], [lo, hi], color=col, linewidth=0.7, zorder=2)
        ax.add_patch(Rectangle((i - body_w / 2, min(o, c)), body_w,
                               max(abs(c - o), 1e-9), facecolor=col,
                               edgecolor="none", zorder=3))

    # recessive grid + month boundaries
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=1)
    ticks, labels = [], []
    for i in range(1, n):
        m_prev, m_cur = hist[i - 1][0][5:7], hist[i][0][5:7]
        if m_prev != m_cur:
            ax.axvline(i - 0.5, color=GRID, linewidth=0.8, zorder=1)
            ticks.append(i - 0.5)
            labels.append(hist[i][0][:4] if m_cur == "01"
                          else _MONTHS[int(m_cur)])
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, fontsize=9, color=MUTED)

    ax.yaxis.tick_right()
    ax.tick_params(axis="y", labelsize=9, colors=MUTED, length=0)
    ax.tick_params(axis="x", colors=MUTED, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xlim(-1, n)
    lo = min(r[3] for r in hist)
    hi = max(r[2] for r in hist)
    pad = (hi - lo) * 0.06 or 1
    ax.set_ylim(lo - pad, hi + pad)

    # last-price dashed line + pill on the price axis
    last_o, last_c = hist[-1][1], hist[-1][4]
    lp_col = UP if last_c >= last_o else DOWN
    ax.axhline(last_c, color=lp_col, linewidth=0.8, linestyle=(0, (2, 2)),
               zorder=4)
    ax.annotate(f"{last_c:,.2f}", xy=(1.0, last_c),
                xycoords=("axes fraction", "data"), xytext=(4, 0),
                textcoords="offset points", fontsize=9, fontweight="bold",
                color="white", va="center", ha="left", zorder=5,
                bbox=dict(boxstyle="round,pad=0.28", facecolor=lp_col,
                          edgecolor="none"))

    # top-left legend, TradingView style
    fig.text(0.015, 0.955, f"{candidate.exchange}:{candidate.ticker}",
             fontsize=11, fontweight="bold", color=INK)
    fig.text(0.015 + 0.017 * len(f"{candidate.exchange}:{candidate.ticker}"),
             0.955, _legend_text(hist), fontsize=9.5, color=MUTED)

    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", facecolor="white")
    finally:
        plt.close(fig)
    return buf.getvalue()


def fetch_chart_png(candidate: Candidate) -> bytes:
    try:
        hist = _fetch_history(candidate.ticker)
    except ChartError:
        raise
    except Exception as e:
        raise ChartError(f"{candidate.ticker}: {e}") from e
    try:
        return _render_png(candidate, hist)
    except Exception as e:
        raise ChartError(f"{candidate.ticker}: render failed: {e}") from e
