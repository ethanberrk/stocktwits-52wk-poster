# Phase 2 — Live Stocktwits Publisher

**Date:** 2026-07-08
**Status:** Approved (design)
**Supersedes nothing; extends** `2026-07-01-stocktwits-52wk-poster-design.md` (Phase 1 dry-run).

## Goal

Replace the Phase‑1 `DryRunPublisher` with a real publisher that posts each
selected 52‑week‑high — `$TICKER` copy **plus the 1‑year TradingView chart PNG**
— to Stocktwits via the CORE `messages/create` API, and bring posting live under
a controlled, ramped rollout.

## Context / what we know

From the colleague Slack thread that granted access:

- Posting uses the **CORE API directly**, not the api‑middleware (that middleware
  is GET‑only: caching/rate‑limiting for reads). POSTs bypass it.
- Auth model is an **OAuth2 access token**. Ethan **has the access_token** in hand
  for the posting/bot account.
- Sanctioned call (text‑only example provided by the vendor):

  ```
  POST https://api.stocktwits.com/api/2/messages/create.json
  Content-Type: application/x-www-form-urlencoded
  User-Agent: ethan-bot/1.0
  access_token=YOUR_ACCESS_TOKEN
  body=YOUR_MESSAGE_BODY
  ```

- The vendor **explicitly flagged Cloudflare bot protection** and asked whether we
  would post from a *predictable set of IPs*. GitHub Actions IPs are unpredictable
  datacenter ranges — exactly what CF bot rules target. This project has already
  observed CF blocking `requests`' TLS fingerprint (403) while `urllib` passes.

### Open unknown: image attachment

The vendor's example is **text‑only**, and `application/x-www-form-urlencoded`
cannot carry a file. Attaching the chart requires `multipart/form-data` with a
file field. Stocktwits' public developer docs are offline ("under review"), and
third‑party wrappers only demonstrate text posts, so the **exact image field name
is unconfirmed**. Historical Stocktwits used a `chart` multipart file field; that
is our best‑guess default.

**Decision (Ethan):** assume image posting works, and confirm it with a single
real live post of an actual 52‑week high + chart. The first live post *is* the
contract test. If it lands text‑only, halt automation and get the image‑variant
curl from the vendor (Victor) before proceeding.

## Non‑goals

- No holiday calendar (still relies on the yfinance quote‑freshness gate).
- No OAuth authorize flow (we already hold a minted access_token).
- No posting from a fixed‑IP proxy yet — revisit only if Actions gets CF‑blocked.
- No change to the source, selection, chart, or state machinery beyond the small
  `run.py` and `config.py` edits below.

## Architecture

The Phase‑1 seam is already in place: `Publisher` ABC + `run.py` marked
`# Phase 2: swap for Stocktwits`. This phase fills that seam.

### 1. `src/publish/stocktwits_pub.py` — `StocktwitsPublisher(Publisher)`

Constructor: `StocktwitsPublisher(access_token, user_agent, url, out_dir, today)`.

`post(candidate, text, image_png) -> PostResult`:

- **Writes the `output/<day>/<TICKER>.png` + `.txt` artifacts first** (identical
  to `DryRunPublisher`), so (a) the nightly audit's `artifacts` check — which
  requires the PNG/txt to exist and agree with state — keeps passing in live
  mode, and (b) we retain a committed, auditable record of every *undeletable*
  post. Artifact‑writing is extracted into a shared helper reused by both
  publishers (no duplicated file logic). Then it posts.
- Builds a **`multipart/form-data`** body (assembled manually — urllib has no
  multipart helper) with three parts:
  - `access_token` — form field, the token.
  - `body` — form field, the composed text.
  - `chart` — file part, `filename="chart.png"`, `Content-Type: image/png`,
    the `image_png` bytes. (Field name `chart` is configurable via a module
    constant so a vendor correction is a one‑line change.)
- Sends via **`urllib.request`** (NOT `requests` — CF blocks requests' TLS
  fingerprint; urllib is proven to pass, including from Actions IPs). Headers:
  `User-Agent` (configurable) and the multipart `Content-Type` with boundary.
- On HTTP 200: parse JSON (`{"response":{"status":200},"message":{"id":…}}`),
  return `PostResult(post_id=str(message.id), dry_run=False)`.
- On any non‑200, Cloudflare block, network error, or unparseable/error‑status
  body: raise `PublishError` (new exception in this module).

Uses the existing `compose_post_text` and `st_symbol` — no copy changes.

### 2. `run.py`

- Add a `--live` flag. Publisher selection:
  - `--live` **and** `STOCKTWITS_ACCESS_TOKEN` present → `StocktwitsPublisher`.
  - otherwise → `DryRunPublisher` (unchanged default — nothing goes live by
    accident, including every existing local/CI dry‑run path).
  - `--live` set but token missing → hard error (exit non‑zero), never silently
    downgrade to dry‑run when a live run was requested.
- In the posting loop, wrap each `publisher.post()` in `try/except PublishError`:
  log and continue to the next ready ticker. A failed post leaves its `pending`
  write‑ahead entry in place.

### 3. `config.py`

- `STOCKTWITS_CREATE_URL = "https://api.stocktwits.com/api/2/messages/create.json"`
- `STOCKTWITS_USER_AGENT = "stocktwits-52wk-poster/1.0"`
- **Launch ramp:** `MAX_PER_TICK = 1`, `MAX_PER_DAY = 3`. (Reverted upward after
  the first clean live week; recorded as a follow‑up.)

### 4. Secrets & workflow

- Local first post: `STOCKTWITS_ACCESS_TOKEN` + `CHART_IMG_API_KEY` exported in
  the shell. Token is **never** committed or pasted into transcripts.
- GitHub repo secret `STOCKTWITS_ACCESS_TOKEN`; `tick.yml` passes it in `env:`
  and adds `--live` to the `run.py` invocation.

## Data flow (unchanged except the final hop)

```
yfinance screen → today's 52wk-high list → validate → pick (cap-limited,
not-blocked) → symbol_exists check → chart-img PNG → write-ahead 'pending'
(+ push in CI) → StocktwitsPublisher.post(multipart) → mark 'posted' w/ id
```

## Error handling & the undeletable‑post contract

Posts are **undeletable**, so the invariant is *at‑most‑once*: never duplicate,
under‑post if uncertain.

- A `pending` write‑ahead entry already blocks re‑selection (`is_blocked`) and
  counts toward `MAX_PER_DAY` (`daily_count`). So a failed/CF‑blocked post is
  **lost for the day, never retried** — the safe side.
- The genuine edge: a post that **succeeds server‑side but returns a
  timeout/CF‑403 to us** → we treat it as failed → ticker stays `pending` →
  we under‑post by one. Never a duplicate. Accepted.
- Per‑ticker try/except means one CF blip cannot cascade to sibling picks in the
  same tick.

## Rollout (approach A — local‑first)

1. Implement + unit‑test the publisher (dry‑run default unchanged).
2. **One real post, locally** (residential IP — directly answers the vendor's
   Cloudflare/predictable‑IP concern; market open, single ticker via
   `MAX_PER_TICK=1`).
3. **Eyeball the live post**: confirm the chart image actually attached (not
   text‑only) and the cashtag/link render correctly.
4. Commit the resulting `state/posted.json` so Actions sees the ticker as posted
   (no same‑day duplicate).
5. Flip `tick.yml` to `--live`; monitor the first automated ticks for CF blocks.
6. Halt conditions: if the local post is text‑only → get the image‑variant curl
   from Victor. If Actions gets CF‑blocked repeatedly → revisit fixed‑IP egress.

## Testing

- `tests/test_publish.py`: unit‑test `StocktwitsPublisher` against a fake
  `urlopen`:
  - multipart body contains all three parts (`access_token`, `body`, `chart`
    with PNG bytes and image/png type);
  - HTTP 200 → parsed `post_id`;
  - error status / bad body → `PublishError`;
  - transport uses urllib (no `requests` import in the publisher);
  - the `output/` PNG+txt artifacts are written on a successful post (so the
    audit stays green in live mode).
  No real token in any test.
- The **local first post** is the live contract test for image attachment.
- Full existing suite (`.venv/bin/python -m pytest`) stays green.

## Follow‑ups (recorded, not in this phase)

- Revert `MAX_PER_TICK`/`MAX_PER_DAY` upward after the first clean live week.
- Fixed‑IP egress for Actions if Cloudflare blocks datacenter IPs in practice.
- Confirm/replace the `chart` multipart field name with Victor's authoritative
  example if the first post disproves it.
