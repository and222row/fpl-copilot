# API

The FastAPI backend serves everything under `/api/v1`. Locally the interactive
docs are at http://localhost:8000/api/docs (Swagger) and `/api/redoc`; both and
`/openapi.json` are switched off in production.

## Conventions

**Authentication.** Clients send the Supabase access token as
`Authorization: Bearer <token>`. The API verifies it locally (see
[AUTHENTICATION.md](AUTHENTICATION.md)) and never issues tokens itself.

**Access levels** in the route table:

| Access | Meaning | Failure |
|---|---|---|
| public | No token needed. A token, if sent, is still verified. | — |
| signed in | A valid token for an account that has not been deleted. | 401 |
| owner | The `{manager_id}` in the path must be the FPL team connected to the caller's account. | 401 without a token, 403 for someone else's team |
| premium | The caller has a live trial or subscription, decided by the server. | 402 with `code: PREMIUM_REQUIRED` and the entitlement |
| operator | `X-Job-Token` header matching `JOB_TOKEN`. In production a missing `JOB_TOKEN` refuses every call (503). | 401 |
| webhook secret | The provider's shared secret (and, for RevenueCat, an HMAC signature). | 401 |

`owner` and `premium` only accept anonymous calls while `AUTH_REQUIRED=false`,
which is a local-development convenience; production runs with it `true`.

**Errors.** Always JSON with a `detail` field. Usually a string; structured
errors carry an object with a machine-readable `code`:

```json
{"detail": {"code": "PREMIUM_REQUIRED", "message": "Your free trial has ended...", "entitlement": {...}}}
{"detail": {"code": "CODE_NOT_FOUND", "message": "...", "attempts_remaining": 7}}
```

A 500 never carries a stack trace; its body has `request_id` instead.

**Request IDs.** Every response has `X-Request-ID` (a caller-supplied value of
up to 64 characters from `[A-Za-z0-9._-]` is reused) and `X-Response-Time-ms`.
Quote the ID when reporting a problem; it finds the log lines and the Sentry
event.

**Rate limits** are per account for signed-in calls and per client IP
otherwise. A 429 body includes the limit.

| Tier | Limit | Used for |
|---|---|---|
| `HEAVY` | 6/minute | Solver runs, rebuilds, history ingest |
| `UPSTREAM` | 30/minute | Calls that fan out to the unofficial FPL API, RevenueCat or Supabase |
| `READ` | 120/minute | Served from our own database |
| default | 240/minute | Everything else |

Limits are off in development and tests.

**Other headers.** `Cache-Control: no-store` by default (responses carry
account data), HSTS outside development, `nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`. Request bodies over 1 MB are refused with 413.

**CORS.** Only origins in `CORS_ORIGINS`, no credentials (bearer tokens, not
cookies), methods GET/POST/PUT/DELETE/OPTIONS.

## Common flows

**App start (signed in):** `GET /me` and `GET /me/entitlements`. No team yet
means onboarding; `premium: false` means the paywall.

**Connecting a team:**

```text
POST /me/fpl-accounts {"fpl_entry_id": 1234567}
  202 {"status": "verification_required", "code": "K7QM2X", "expires_at": ..., "instructions": ...}
      (200 {"status": "connected"} if it is already yours)
user adds K7QM2X to their FPL team name
POST /me/fpl-accounts/1234567/verify
  201 {"status": "connected", "trial_started": true, "entitlement": {...}}
  422 CODE_NOT_FOUND (name not changed yet), 429 after 10 attempts, 404 if the code expired (30 min)
```

**After a purchase or restore:** `POST /billing/sync` (no body). The server
reads the caller's state from RevenueCat and returns the new entitlement.

**The main screen:** `GET /fpl/gameweek`, then `GET /decisions/{manager_id}`
(lineup, captain, issues and recommended transfer in one call; can take tens
of seconds on a cold solve, so the app allows 60 s).

**Recording transfers FPL cannot show yet:**
`POST /fpl/manager/{manager_id}/squad-state/transfers` with
`{"moves": [{"out": 1, "in": 572}]}`. See
[DESIGN_NOTES.md](DESIGN_NOTES.md#a-hard-limit-we-cannot-see-your-pending-transfers).

**Operator refresh:** `POST /jobs/refresh` with `X-Job-Token`. Runs sync →
change detection → team strength → projections → alerts → notifications →
push, each step isolated, and returns a per-step report. The scheduler calls
this; see [ARCHITECTURE.md](ARCHITECTURE.md#the-refresh-pipeline).

## Routes

Generated from the application by `backend/scripts/api_reference.py`; do not
edit the table by hand. `tests/test_docs.py` fails when it is out of date:

```bash
cd backend
python scripts/api_reference.py
```

The purpose column is the first sentence of each endpoint's docstring; query
parameters and response shapes are in the Swagger UI.

<!-- BEGIN GENERATED ROUTES -->
### health

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/health` | public | default | Liveness plus dependency reachability. |
| GET | `/api/v1/health/ops` | operator | default | Operator view: background jobs, billing webhooks, external services. |
| GET | `/api/v1/health/freshness` | public | default | How stale is every data set we depend on? |
| GET | `/api/v1/health/cache` | public | default | Hit rate for the FPL response cache. |

### fpl

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| POST | `/api/v1/fpl/sync/bootstrap` | operator | HEAVY | Pull latest teams, gameweeks and players from FPL into our database. |
| POST | `/api/v1/fpl/sync/fixtures` | operator | HEAVY | Pull all season fixtures from FPL. |
| GET | `/api/v1/fpl/gameweek` | public | default | The gameweek the dashboard works on: the next one with an OPEN deadline. |
| GET | `/api/v1/fpl/players` | public | default | Players from the synced FPL data, filtered and sorted. |
| GET | `/api/v1/fpl/players/{player_id}` | public | default | One player's synced FPL data. |
| GET | `/api/v1/fpl/teams` | public | default | All 20 clubs with their strength ratings. |
| GET | `/api/v1/fpl/fixtures` | public | default | Fixtures, optionally for one gameweek or club. |
| GET | `/api/v1/fpl/manager/{manager_id}` | owner | UPSTREAM | Manager profile straight from FPL — no local data needed. |
| GET | `/api/v1/fpl/manager/{manager_id}/squad` | owner | UPSTREAM | A manager's 15-player squad, enriched with our player data. |
| GET | `/api/v1/fpl/manager/{manager_id}/squad-state` | owner | default | Which squad the app believes you hold, and where that came from. |
| POST | `/api/v1/fpl/manager/{manager_id}/squad-state/transfers` | owner | UPSTREAM | Tell the app about transfers you have already made. |
| DELETE | `/api/v1/fpl/manager/{manager_id}/squad-state` | owner | default | Discard the override and go back to what FPL reports. |

### projections

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| POST | `/api/v1/projections/rebuild/team-strength` | operator | HEAVY | Recompute custom fixture-difficulty ratings from results so far. |
| POST | `/api/v1/projections/rebuild` | operator | HEAVY | Rebuild player projections. |
| GET | `/api/v1/projections` | premium | default | Top projected players for a gameweek. |
| GET | `/api/v1/projections/player/{player_id}` | premium | default | Full projection breakdown for one player across upcoming gameweeks. |
| GET | `/api/v1/projections/team-strength` | premium | default | Derived attack/defence ratings behind the custom FDR. |
| POST | `/api/v1/projections/backtest/ingest-history` | operator | HEAVY | Pull per-GW actual results for the backtest ground truth. |
| GET | `/api/v1/projections/backtest` | public | default | Score stored projections against recorded actuals. |

### decisions

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/decisions/{manager_id}/lineup` | owner + premium | UPSTREAM | Optimal starting XI, bench order, captain and vice. |
| GET | `/api/v1/decisions/{manager_id}/captain` | owner + premium | UPSTREAM | Captain ranking under all three risk modes, side by side. |
| GET | `/api/v1/decisions/{manager_id}/transfers` | owner + premium | HEAVY | Best transfer options over a horizon, compared against rolling. |
| GET | `/api/v1/decisions/{manager_id}` | owner + premium | HEAVY | The dashboard's primary call: lineup, captain, squad issues and the recommended transfer, in one response. |

### news

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| POST | `/api/v1/news/detect` | operator | HEAVY | Diff current player state against the last snapshot and log any changes. |
| GET | `/api/v1/news/events` | public | default | Chronological availability feed, newest first. |
| POST | `/api/v1/news/alerts/{manager_id}/generate` | owner + premium | UPSTREAM | Raise alerts for changes affecting this manager's squad. |
| GET | `/api/v1/news/alerts/{manager_id}` | owner + premium | default | This manager's alerts, newest first. |
| POST | `/api/v1/news/alerts/{manager_id}/read` | owner + premium | default | Mark one alert, or all of them, as read. |
| GET | `/api/v1/news/price-watch` | public | default | Players near a price change, from FPL's own published projections. |
| GET | `/api/v1/news/parse-check` | public | default | Show how the parser reads every current news string. |

### feedback

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/feedback/{manager_id}/accuracy` | owner + premium | default | Running accuracy across every scored gameweek, per decision category. |
| GET | `/api/v1/feedback/{manager_id}/history` | owner + premium | default | Per-gameweek outcomes, newest first. |
| GET | `/api/v1/feedback/{manager_id}/pending` | owner + premium | default | Recommendations saved but not yet scored. |
| POST | `/api/v1/feedback/{manager_id}/score` | owner + premium | UPSTREAM | Grade the recommendations saved for a finished gameweek. |
| POST | `/api/v1/feedback/{manager_id}/score-all` | owner + premium | HEAVY | Score every gameweek that has recommendations awaiting a grade. |

### planner

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/planner/{manager_id}` | owner + premium | HEAVY | Multi-gameweek transfer plan as a branching decision tree. |

### jobs

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| POST | `/api/v1/jobs/refresh` | operator | HEAVY | Bring everything up to date: sync, detect changes, rebuild, raise alerts. |
| GET | `/api/v1/jobs/status` | operator | default | Whether background refresh is on, and who it generates alerts for. |
| POST | `/api/v1/jobs/track/{manager_id}` | operator | default | Register a team ID for background alerts. |
| DELETE | `/api/v1/jobs/track/{manager_id}` | operator | default | Stop generating background alerts for a team ID. |

### dream-team

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/dream-team` | premium | HEAVY | The best legal 15 from the entire player pool — ignoring what you own. |

### notifications

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/notifications/{manager_id}` | owner | READ | Whether this manager has Telegram linked, and whether it is active. |
| POST | `/api/v1/notifications/{manager_id}/telegram/link` | owner | UPSTREAM | Mint a single-use deep link that connects a Telegram chat to this squad. |
| POST | `/api/v1/notifications/{manager_id}/telegram/enabled` | owner | UPSTREAM | Pause or resume delivery without discarding the link. |
| DELETE | `/api/v1/notifications/{manager_id}/telegram` | owner | UPSTREAM | Forget the chat entirely. |
| POST | `/api/v1/notifications/{manager_id}/telegram/test` | owner | UPSTREAM | Prove the link works, rather than waiting for a player to get injured. |
| POST | `/api/v1/telegram/webhook` | webhook secret | default | Receive updates from Telegram. |

### chips

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/chips/{manager_id}` | owner + premium | HEAVY | When to play each chip, for this squad. |
| GET | `/api/v1/chips/fixtures/shape` | public | READ | Which gameweeks contain doubles or blanks. |

### me

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/me` | signed in | default | The caller's identity (from the token) and connected FPL team. |
| GET | `/api/v1/me/entitlements` | signed in | default | Whether the caller has premium access right now. |
| POST | `/api/v1/me/fpl-accounts` | signed in | UPSTREAM | Begin connecting a team: confirm it exists, then issue the code that proves control of it. |
| POST | `/api/v1/me/fpl-accounts/{fpl_entry_id}/verify` | signed in | UPSTREAM | Check FPL for the code in the team name; on success the team is yours. |
| DELETE | `/api/v1/me/fpl-accounts/{fpl_entry_id}` | signed in | default | Disconnect a team and drop its private state (overrides, alert links). |
| PUT | `/api/v1/me/devices` | signed in | default | Register this install for push. |
| DELETE | `/api/v1/me/devices/{token}` | signed in | default | Stop pushes to this install, called on sign-out. |
| GET | `/api/v1/me/notifications` | signed in | default | Which push notification kinds are on (all on until changed). |
| PUT | `/api/v1/me/notifications` | signed in | default | Switch push notification kinds on or off; omitted kinds are unchanged. |
| DELETE | `/api/v1/me` | signed in | UPSTREAM | Permanently delete the account and the data held about it. |

### players

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/players` | premium | READ | Search, filter and sort every player, with next-gameweek projections. |
| GET | `/api/v1/players/{player_id}` | premium | UPSTREAM | Everything the player screen shows, in one round trip. |

### billing

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| POST | `/api/v1/billing/revenuecat/webhook` | webhook secret | default | Subscription events from RevenueCat, used as a cue to re-read the customer. |
| POST | `/api/v1/billing/sync` | signed in | UPSTREAM | Called by the app right after a purchase or restore, so access does not wait for the webhook. |

### leagues

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/leagues/{manager_id}` | owner + premium | UPSTREAM | Your classic mini-leagues, your own first, with your rank in each. |
| GET | `/api/v1/leagues/{manager_id}/{league_id}` | owner + premium | UPSTREAM | A league's table with your gaps, the players the leaders own that you don't, and your differentials. |
| GET | `/api/v1/leagues/{manager_id}/{league_id}/rivals/{rival_id}` | owner + premium | UPSTREAM | Head to head with one rival: shared players, the differences, and who they favour. |

### root

| Method | Path | Access | Rate limit | Purpose |
|---|---|---|---|---|
| GET | `/` | public | default | Service name and version. |
<!-- END GENERATED ROUTES -->
