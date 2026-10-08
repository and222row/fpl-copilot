# Architecture

How FPL Copilot is put together: the pieces, how a request flows, where data
lives, and the rules the code relies on. The reasoning behind individual
features (the projection model, the optimisers, the planner) is in
[DESIGN_NOTES.md](DESIGN_NOTES.md).

## System

```text
  ┌──────────────┐   ┌──────────────┐
  │  Mobile app  │   │ Web dashboard│        Apple / Google sign-in
  │ Expo, iOS +  │   │  Next.js on  │──┐           │
  │   Android    │   │   Vercel     │  │           ▼
  └──────┬───────┘   └──────┬───────┘  └────► Supabase Auth ──► access token (JWT)
         │  HTTPS, Bearer token                      │ JWKS
         ▼                  ▼                        ▼
  ┌─────────────────────────────────────────────────────────┐
  │ FastAPI on Render                                       │
  │  middleware: request id → security headers → CORS →     │
  │              body limit → rate limits                   │
  │  auth: verify JWT · ownership · premium · operator      │
  │  routers ─► services (projection, optimisers, planner,  │
  │             news, alerts, entitlements, billing, push)  │
  └──┬──────────────┬───────────────┬───────────────┬───────┘
     │              │               │               │
     ▼              ▼               ▼               ▼
  Postgres       Upstash Redis    FPL public API   RevenueCat ◄── App Store / Google Play
  (Supabase)     (cache only)     (unofficial)        │
                                                      └─ webhook ──► FastAPI
  Expo push ──► APNs / FCM        Telegram bot API    Sentry · Healthchecks.io

  QStash (every 30 min) and GitHub Actions (backup) ──► POST /api/v1/jobs/refresh
```

| Component | Role |
|---|---|
| Mobile app (`mobile/`) | The product. Sign-in, onboarding, paywall and every feature. See [MOBILE_APP.md](MOBILE_APP.md). |
| Web dashboard (`frontend/`) | The same advice in a browser, for signed-in users with access. Sells nothing. |
| API (`backend/`) | All logic and all decisions about access. Stateless; any instance can serve any request. |
| Postgres (Supabase) | System of record: FPL data, model output, accounts, trials, subscriptions, alerts. |
| Supabase Auth | Identities, sign-in, token issue and refresh. The API only verifies tokens. |
| Redis (Upstash) | Short-lived cache of per-manager FPL reads. Fails open: the API works without it. |
| FPL API | Source of players, fixtures, prices, news and squads. Unofficial, unauthenticated. |
| RevenueCat | Receipt validation and subscription state for both stores. |
| Expo push | Delivers push notifications through APNs and FCM. |
| QStash / GitHub Actions | Trigger the scheduled refresh from outside (the free API instance sleeps). |
| Sentry / Healthchecks.io | Error and crash tracking; the refresh heartbeat. See [OBSERVABILITY.md](OBSERVABILITY.md). |

The original blueprint's diagram also listed a football data API, OpenAI and
external news sources. None is used: FPL's own data covers fixtures and
availability, its news field is formulaic enough to parse without a language
model, and the optimisers are deterministic.

## Backend layout

```text
backend/app/
├── main.py            app, middleware, exception handlers, router registration
├── config.py          settings from the environment
├── auth.py            token verification and the access dependencies
├── security.py        body size limit, production self-checks
├── observability.py   JSON logs, redaction, request ids, Sentry
├── rate_limit.py      limiter and tiers
├── database.py        async SQLAlchemy engine and sessions
├── redis_client.py    Redis with reconnection
├── scheduler.py       optional in-process refresh loop (local only)
├── routers/           HTTP layer: validation, access, response shape
├── services/          the logic, unit tested without HTTP
└── models/            SQLAlchemy tables
```

Routers stay thin: they declare access with dependencies and call services.
Services never trust anything about identity they did not receive from
`auth.py`.

Main services:

| Area | Modules |
|---|---|
| FPL data | `fpl_client` (HTTP, caching), `fpl_sync` (upserts, gameweek helpers), `cache`, `sync_gate` |
| Model | `projection`, `team_strength`, `confidence`, `backtest` |
| Decisions | `lineup` (exact XI and captain), `transfers` (CP-SAT), `dream_team`, `planner` (beam search), `chips`, `transfer_reasons`, `player_view` |
| Squads | `squad_state` (pending-transfer overrides; the only way to read a squad) |
| News and alerts | `news_parser`, `news_taxonomy`, `change_detection`, `notifications`, `telegram`, `push` |
| Accounts and billing | `entitlements`, `revenuecat`, `accounts`, `supabase_admin` |
| Operations | `jobs` (the refresh), `job_monitor`, `upstreams`, `feedback` (accuracy) |

## A request, end to end

`GET /api/v1/decisions/{manager_id}` from the app:

1. **Request context** assigns or reuses the request ID; everything logged
   from here on carries it.
2. **Security headers, CORS, body limit, rate limit** (per account once the
   token is verified, per IP otherwise).
3. **Auth dependencies:** the token is verified locally against Supabase's
   JWKS; `ManagerAccess` checks the team is connected to this user;
   `Premium` asks the entitlement service. Any failure stops here with 401,
   403 or 402.
4. **Router → services:** `resolve_squad` gets the squad the manager actually
   holds (FPL picks plus any recorded pending transfers), projections come
   from Postgres, the lineup is solved exactly and transfers by CP-SAT.
5. **Snapshot:** if the deadline has not passed, the advice is recorded for
   later accuracy scoring.
6. **Response** with `X-Request-ID`, `X-Response-Time-ms`, `no-store`.

## The refresh pipeline

`POST /api/v1/jobs/refresh` (operator token) is the single entry point for
scheduled work, so every trigger does identical work (`services/jobs.py`):

```text
bootstrap      players, prices, news, scoring rules         ─┐
fixtures       results                                        │ always
detect         diff against the last sync → events          ─┘
team strength  custom fixture difficulty                     ─┐ only if something
projections    expected points, 5 gameweeks                  ─┘ changed
verified       stamp "data confirmed current"
alerts         per tracked team, from the events
gameweek shape new doubles and blanks
notifications  Telegram
push           Expo, for users who opted in
```

Each step is isolated: a failure is recorded and the rest still run. The run
is stored in `job_runs` and pinged to Healthchecks.io. Rebuilding is skipped
when nothing moved, which is what keeps the free database bandwidth
allowance intact.

## Data model

Tables by area (all in Postgres; `alembic/versions/` creates them):

| Area | Tables | Notes |
|---|---|---|
| FPL data | `teams`, `players`, `gameweeks`, `fixtures`, `player_gameweek_stats`, `scoring_rules`, `chip_windows`, `sync_state` | Upserted by the refresh; rows only rewritten when they change. |
| Model output | `projections`, `team_strength` | Rebuilt by the refresh. |
| News and alerts | `availability_events`, `player_availability_snapshots`, `alerts`, `tracked_managers`, `telegram_links` | Alerts are per FPL team. |
| Squads and accuracy | `squad_overrides`, `recommendation_snapshots`, `recommendation_outcomes` | Per FPL team. |
| Accounts | `users`, `fpl_accounts`, `fpl_claims`, `trials`, `deleted_users` | `users.id` is the Supabase user id. |
| Billing | `subscriptions`, `billing_events` | Written only from RevenueCat's API. |
| Notifications | `devices`, `notification_preferences`, `push_deliveries` | |
| Operations | `job_runs` | 30-day retention. |

Relationships that matter:

```text
users 1──1 fpl_accounts ──(fpl_entry_id)── tracked_managers, alerts,
  │                                       squad_overrides, snapshots
  ├──1 trials (keyed by fpl_entry_id; user set null on deletion)
  ├──1 subscriptions
  └──* devices, notification_preferences, push_deliveries
```

Compared with the spec's list: there is no `auth_identities` table (Supabase
keeps identities in its own `auth.identities`, and the API never needs them)
and no `entitlements` table (entitlement is computed from `trials` and
`subscriptions` on each request, so it cannot drift).

Email and phone are never stored by the backend. Every public table has row
level security enabled with no policies, so Supabase's Data API cannot reach
them with the publishable key; the backend connects as the owner role.

## Rules the code relies on

- **The server decides access.** Clients never supply a user id, entitlement,
  price or plan that is trusted; screens in the app only decide navigation.
- **Every path that reads a squad calls `resolve_squad`**, never
  `fetch_manager_picks` directly (the one exception is post-gameweek scoring,
  which wants what actually happened). FPL cannot show transfers made before
  a deadline, and bypassing the override layer has caused stale advice and
  alerts about sold players more than once.
- **Advice targets the next gameweek with an open deadline**; squads are read
  from the latest gameweek that has started. They differ mid-season.
- **The bootstrap and fixtures are never cached**: change detection needs to
  see the real current state.
- **Every outbound HTTP client uses `transport=monitored("<provider>")`**, so
  upstream health is tracked; a test enforces it.
- **Time is the server's.** Trial and subscription expiry use the server
  clock at request time.
- **Fail open where it is safe, closed where it is not.** Redis, Telegram,
  push and monitoring failures never fail a request or a refresh; missing
  security configuration in production refuses requests instead.

## Decisions

| Decision | Why | Alternative rejected |
|---|---|---|
| Supabase Auth, verified locally | Free, Apple and Google built in, no auth server to run; local JWT verification keeps Supabase off the request path. | Own auth service; Firebase Auth. |
| Team ownership by a code in the FPL team name | FPL has no OAuth; team IDs are public, so first-come claiming allowed squatting. | Trusting the entered ID. |
| Store billing through RevenueCat | Required for in-app digital subscriptions; RevenueCat handles both stores' receipts and renewals for free at this scale. | Direct StoreKit/Play Billing validation; Stripe in the app. |
| Entitlement computed, not stored | One function answers "premium?" from trials and subscriptions on the server clock; nothing to keep in sync. | An entitlements table updated by webhooks. |
| Expo (React Native) for the app | One codebase for both platforms, cloud builds without local Xcode or Android Studio, good native module support. | Two native apps; Flutter. |
| Deterministic optimisers (exact search, CP-SAT) | Provably optimal or explicitly not; reproducible; explainable with numbers. | LLM-generated advice. |
| Regex news parsing | FPL's news field is formulaic; 100% of live strings parse. | An LLM extraction step. |
| External scheduler hitting one endpoint | The free API instance sleeps, so an in-process loop dies; QStash keeps time where GitHub Actions does not. | APScheduler or Celery in-process. |
| Render free tier | Cost. Cold starts and bandwidth limits are handled in code. | Paid hosting. |
| Sentry for errors and crashes | One free tool for API and both app platforms. | Crashlytics plus a separate API tracker. |
