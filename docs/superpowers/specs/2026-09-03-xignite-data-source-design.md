# Xignite data source + shadow mode + one-setting revert

**Goal.** Replace every scraped feed (Yahoo screener, Yahoo v7 quotes,
stockanalysis.com, WSJ list) with Ethan's licensed Xignite subscription,
without changing what gets posted, and with a switch that can be flipped back
in seconds if the new data misbehaves.

## Data mapping

| Need | Today (scraped) | Xignite |
|---|---|---|
| US-listed universe | Yahoo screener | SEC `company_tickers_exchange.json` (Nasdaq/NYSE rows; keyless, official) |
| Day high/low, 52wk high/low, price, %chg, volume, exchange, name, freshness | Yahoo screener rows | `GlobalQuotes.GetGlobalDelayedQuotes`, 500 symbols/call, 15-min delayed |
| Market cap | Yahoo `marketCap` | `FactSetFundamentals.GetFundamentals` (MarketCapitalization, Millions), only for names that pass the 52-wk test |
| 1Y daily candles | stockanalysis.com | `GlobalHistorical.GetGlobalHistoricalQuotesRange` (SplitOnly) + today's candle from the delayed quote |
| Cashtag check, watchers | Stocktwits public endpoint | unchanged |

Symbology: SEC uses dashes (`BRK-B`), Xignite uses dots (`BRK.B`); the
Candidate keeps the dash form so state/cooldown files stay compatible.
Preferreds/warrants/units are dropped by symbol shape (`-P?`, `-WT/-RT/-UN`,
5-letter `W/R/U`) before quoting.

Freshness gate: quote `Date` must equal today (ET). 52-wk test is
day-cumulative: `High >= High52Weeks` (Xignite's 52-wk figure already
includes today, verified 2026-09-03).

## The switch (revert path)

`DATA_SOURCE` env var, values `legacy` (default) | `xignite`. Read once in
`config.py`; picks both the candidate source AND the chart-history source.
In CI it is `${{ vars.DATA_SOURCE || 'legacy' }}` — a GitHub **repository
variable** changed in Settings → Secrets and variables → Actions → Variables.
No code change, no deploy: flip to `xignite` to go live, back to `legacy` to
revert. `--source` CLI flag overrides for local runs.

`xignite` without `XIGNITE_TOKEN` is a hard SourceError (tick fails red, never
silently posts from a different feed).

## Shadow mode (watch before switching)

After every live tick, a separate step runs `scripts/shadow.py`: it fetches
candidates from the source that is NOT active, compares against the active
source's candidates (dumped by the tick to `shadow/<date>/<HHMM>.active.json`),
and writes `shadow/<date>/<HHMM>.json`:

```
{ "active": "legacy", "shadow": "xignite", "counts": {...},
  "only_in_active": [...], "only_in_shadow": [...],
  "would_pick": {"legacy": [...], "xignite": [...]} }
```

`would_pick` replays `select.pick` with the same posted-state, so we can see
whether the two feeds would have chosen the same tickers. The step is
`continue-on-error`, touches no state, and is committed with the tick's
state/output. `scripts/shadow_report.py [date]` prints the day's agreement.
Shadow keeps running after the switch (roles reversed) until `vars.SHADOW=off`.

## Out of scope

Real-time (SuperQuotes) quotes; Firestream; changing caps, copy, ranking or
any owner-locked rule. Same plan ported to lows / RS / RW after highs proves
out.
