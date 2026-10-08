# Observability

How FPL Copilot reports problems, what each signal covers, how to switch it on,
and where to look when something breaks. Everything here is on a free tier
and turned off until its setting is filled in.

| Need | What does it | Where it shows |
|---|---|---|
| Structured logging | JSON logs with `request_id`, redaction of credential and personal keys (`backend/app/observability.py`) | Render → Logs |
| API error tracking | Sentry (`SENTRY_DSN`): unhandled exceptions, 5xx responses, every `ERROR` log | Sentry issues + email |
| Crash reporting (app) | Sentry React Native (`EXPO_PUBLIC_SENTRY_DSN`): native crashes, JS errors, render errors caught by the root error screen | Sentry issues + email |
| Background-job monitoring | Each refresh stored in `job_runs`; Healthchecks.io heartbeat (`HEALTHCHECKS_PING_URL`) | Healthchecks.io email, `/api/v1/health/ops` |
| Payment webhook monitoring | `billing_events` audit trail, outcome logs, rejection counter, escalation of events still failing after an hour | Sentry, `/api/v1/health/ops` |
| External API health | Every outbound client records outcomes per provider: FPL, RevenueCat, Expo push, Supabase auth/admin, Telegram | Sentry (once per outage), `/api/v1/health/ops` |

## Setup

### Sentry (backend and app)

1. Create a free account at sentry.io (check current plan limits on their
   pricing page). Choose the EU data region if your users are mostly in
   Europe; it cannot be changed later.
2. Create two projects: **Python / FastAPI** for the API and **React Native**
   for the app. Separate projects keep app crashes and API errors apart.
3. API: put the FastAPI project's DSN in Render as `SENTRY_DSN`. `RELEASE`
   needs no setting on Render; it reads `RENDER_GIT_COMMIT`.
4. App: put the React Native project's DSN in the EAS environment
   (`production`, and `preview` if wanted) as `EXPO_PUBLIC_SENTRY_DSN`. For
   readable stack traces also set `SENTRY_ORG`, `SENTRY_PROJECT` and, as a
   **sensitive** variable, `SENTRY_AUTH_TOKEN` (an organisation token with
   release upload scope). Without the last three, crashes are still reported
   but stack traces are minified.
5. In each project: **Settings → Client Keys → Rate limiting**, set something
   like 100 events per hour, and keep spike protection on. This stops one
   runaway loop from using up the month's free quota.
6. Alerts: the default "new issue" email alert is enough to start. Add a
   "number of events > 20 in 1 hour" alert on the API project if you want to
   hear about a recurring issue, not only a new one.

### Healthchecks.io (scheduled refresh)

1. Create a free account and a check named `fpl-copilot refresh`.
2. Period **30 minutes** (the QStash schedule), grace **60 minutes**. A
   refresh takes up to a few minutes on a cold instance, and the grace keeps
   one dropped delivery from paging you.
3. Copy the ping URL into Render as `HEALTHCHECKS_PING_URL`.

Each refresh pings `/start`, then the bare URL on success or `/fail` with the
failing step names. You get an email when a run fails, when one starts but
never finishes, or when none arrives for 90 minutes. That last case is the one
nothing inside the API can detect: QStash stopped delivering, the API was
down, or the service was suspended.

### Optional: uptime check

Point a free uptime monitor (UptimeRobot, Better Stack) at
`GET /api/v1/health`, which is public and returns `"status": "ok"` or
`"degraded"`. Note that a 5-minute check keeps Render's free instance awake
around the clock, which uses most of its monthly free hours. The heartbeat
above already notices the API being unreachable, within 90 minutes.

## The operator endpoint

```bash
curl -s -H "X-Job-Token: $JOB_TOKEN" https://<api>/api/v1/health/ops
```

Returns `status` (`ok` or `degraded`) and a `problems` list, empty when
healthy, plus the detail behind it:

- `jobs.refresh`: the last run, its errors, the last success and the current
  failure streak. It is a problem if the last run failed or there has been no
  success for 95 minutes.
- `billing`: last webhook received and processed, deliveries in 24 hours,
  unprocessed events, events still unprocessed after an hour (a problem), and
  deliveries refused since start, with the reason (authorization, signature,
  too large, malformed).
- `upstreams`: per provider, calls, failures, the current streak, last status,
  last error type and latency. A provider is `down` after 3 consecutive
  failures (5xx, 429 or a connection error; other 4xx are our requests and do
  not count). Process-local: it resets when the instance restarts.
- `monitoring`: whether Sentry and the heartbeat are configured, and the
  running release.

## What leaves our systems

The store privacy forms and the spec both depend on this, so it is enforced in
code and tested (`backend/tests/test_monitoring.py`,
`mobile/src/lib/__tests__/monitoring.test.ts`).

**API → Sentry:** exception type, message and stack trace (code lines, no local
variable values), the route and method, request headers with credentials
redacted, the request ID, environment and release. **Not sent:** request
bodies, cookies, local variables, user ID or email, IP address. ERROR log
records go as events with their extra fields scrubbed by the same redaction
list as the logs; warnings and below are never sent.

**App → Sentry:** crash or error stack traces, device model and OS version,
app version, navigation breadcrumbs, and request URLs without query strings.
**Not sent:** user identity, IP address, screenshots, view hierarchy, request
headers or bodies, console output. Development and e2e builds send nothing.

For the **App Store privacy label**, declare *Diagnostics → Crash Data* (and
*Performance Data* only if tracing is ever turned on): not linked to the
user, not used for tracking. For **Google Play data safety**, declare *App info
and performance → Crash logs, Diagnostics*: collected, not shared (Sentry is a
service provider), processed ephemerally is *no*, collection is required.

**API → Healthchecks.io:** the failing step names and their short messages.
No user data passes through the refresh's error messages, but read them
before widening access to the Healthchecks account.

## When something breaks

**A user reports an error.** Find the request by time and route in Render's
logs, or by request ID: every response carries `X-Request-ID`, a 500's body
includes it, and every log line and Sentry event from that request carries it
too (`request_id` tag).

**Healthchecks says the refresh failed.** The email names the failing step.
`/health/ops` → `jobs.refresh.last_run.errors` has the message; Sentry has the
traceback (`refresh step failed`). FPL being down shows as `upstreams.fpl`
down, and the next successful refresh closes the alert by itself.

**Healthchecks says the refresh is late.** Nothing arrived. Check, in order:
Render (suspended or crashed?), QStash (`python scripts/qstash_schedule.py
list`, delivery logs in the Upstash console), and `JOB_TOKEN` (a mismatch
returns 401 to QStash and never reaches the job).

**Purchases are not unlocking.** `/health/ops` → `billing`:

- `rejected.since_start` rising with reason `authorization` or `signature`:
  the webhook secrets in RevenueCat and Render differ.
- `overdue` events with a RevenueCat error: the API cannot reach RevenueCat
  (see `upstreams.revenuecat`). RevenueCat keeps retrying for a while, and the
  app's own `/billing/sync` after a purchase does not depend on the webhook.
- Nothing received at all: check the webhook URL in RevenueCat.

**Pushes are not arriving.** `upstreams.expo_push`, and the `push` step in the
last refresh. Tokens Expo reports as unregistered are deleted automatically,
so a user who reinstalled must open the app once to register again.

## Decisions

- **One tool for errors and crashes.** Sentry covers the API and both app
  platforms on one free account. Firebase Crashlytics would add a second
  console and native Firebase configuration for no extra coverage.
- **No OpenTelemetry collector.** Nothing free would receive the traces, and
  at this scale structured logs plus request IDs answer the questions traces
  would. Sentry tracing is available by raising `SENTRY_TRACES_SAMPLE_RATE`.
- **No active probing of providers.** The scheduled refresh already calls FPL
  every 30 minutes and pushes call Expo; probing on top would spend FPL's
  goodwill and Upstash requests to learn the same thing.
- **The web dashboard is not instrumented.** It is a thin client over the
  same API, whose errors Sentry already sees. Add `@sentry/nextjs` if
  browser-side errors become a concern; its ingest host must then be added
  to the site's `connect-src`.
