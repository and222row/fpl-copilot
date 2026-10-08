# Deployment

Where each piece runs, how to deploy it the first time and afterwards, and how
to release the mobile app. Everything is on a free tier except the store
developer accounts. Nothing here publishes automatically: store submissions,
migrations and production secrets are always a deliberate manual step.

## Hosts

| Piece | Host | Config |
|---|---|---|
| API | Render (free web service, Docker, Frankfurt) | `render.yaml` blueprint, `backend/Dockerfile` |
| Web dashboard | Vercel (Hobby) | Root directory `frontend` |
| Database and auth | Supabase (free) | Alembic migrations; Auth providers in the dashboard |
| Cache | Upstash Redis (free) | `REDIS_URL` |
| Scheduler | Upstash QStash (primary), GitHub Actions (backup) | `backend/scripts/qstash_schedule.py`, `.github/workflows/refresh.yml` |
| Billing | RevenueCat (free tier) + App Store + Google Play | see [PAYMENTS.md](PAYMENTS.md) |
| Push | Expo push service → APNs / FCM | EAS credentials |
| Monitoring | Sentry, Healthchecks.io (free) | see [OBSERVABILITY.md](OBSERVABILITY.md) |
| App builds | EAS Build (free tier) | `mobile/eas.json` |

Every setting is described in
[ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md).

## First deployment

1. **Rotate credentials** if a Supabase password, Upstash token or any key
   has ever been pasted into a chat, ticket or commit.
2. **Supabase:** create the project. Configure Auth as in
   [AUTHENTICATION.md](AUTHENTICATION.md#setup-checklist) (Apple, Google,
   email off, 15-minute JWT expiry). Run the migrations from your machine:

   ```bash
   cd backend
   DATABASE_URL="postgresql+asyncpg://..." alembic upgrade head
   ```

   Then check Supabase → Advisors → Security shows no table without RLS, and
   that the Data API refuses the publishable key:

   ```bash
   curl "$SUPABASE_URL/rest/v1/users" -H "apikey: <publishable key>"
   ```

3. **Render:** New → Blueprint → this repository. It reads `render.yaml` and
   prompts for every `sync: false` value. Leave `CORS_ORIGINS` until step 4
   gives you the web domain. `ENVIRONMENT=production`, `AUTH_REQUIRED=true`
   and `TRUSTED_PROXY_HOPS=1` come from the blueprint. On startup the API logs
   `security self-check:` errors for anything missing; there should be none.
4. **Vercel:** import the repository and set **Root Directory to `frontend`**
   (the repository root has no `package.json`, so git-triggered builds from
   `.` fail while CLI deploys from inside `frontend/` still work, which hides
   the mistake). Set `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL` and
   `NEXT_PUBLIC_SUPABASE_KEY`, and link the Vercel project to GitHub, or
   pushes deploy the API but silently leave the web on its previous build.
   Then add the Vercel domain to Render's `CORS_ORIGINS` and to Supabase's
   Redirect URLs, and redeploy the API.

   **Order matters:** the web needs its Supabase variables before the API runs
   with `AUTH_REQUIRED=true`, or the dashboard cannot sign in and every team
   request is refused.
5. **Scheduler:** with `QSTASH_TOKEN`, `JOB_TOKEN` and `API_BASE_URL` in
   `backend/.env`:

   ```bash
   python scripts/qstash_schedule.py create --cron "*/30 * * * *"
   python scripts/qstash_schedule.py test
   ```

   Every 30 minutes keeps database bandwidth and QStash's daily message
   allowance comfortable (the script's `*/15` default predates the bandwidth
   fix; see [DESIGN_NOTES.md](DESIGN_NOTES.md#bandwidth-the-refresh-was-rewriting-the-database-to-say-nothing-happened)).
   For the backup, add `API_BASE_URL` and `JOB_TOKEN` as GitHub Actions
   secrets and run *Scheduled refresh* once by hand.
6. **RevenueCat, stores and webhook:** [PAYMENTS.md](PAYMENTS.md#setup-checklist).
7. **Monitoring:** Sentry projects and Healthchecks.io check, as in
   [OBSERVABILITY.md](OBSERVABILITY.md#setup).
8. Confirm: `GET /api/v1/health` returns `ok`; `GET /api/v1/health/ops` with
   the job token returns no problems after the first refresh; the web
   dashboard signs in.

## Routine deploys

- **API:** push to `main`; Render rebuilds the Docker image and deploys. If a
  release needs a schema change, run `alembic upgrade head` against Supabase
  **before** pushing: there is no release-phase hook on the free plan.
  Migrations must be additive or backwards compatible with the running code,
  because the old version keeps serving until the new one is live.
- **Web:** push to `main`; Vercel builds `frontend/`. Changing a
  `NEXT_PUBLIC_` variable needs a redeploy, since they are inlined at build.
- **After a suspension:** Render resumes the image it had, not the newest
  commit. Check which commit is running (`release` in `/health/ops`, or the
  `starting up` log line) and trigger a manual deploy if needed.

### Migrations

```bash
cd backend
alembic upgrade head              # apply
alembic current                   # where the database is
alembic downgrade -1              # one step back (read the migration first)
.\migrate.bat "what changed"      # Windows: generate from model changes, then apply
```

Rules: never edit a migration that has run in production; add a new one.
Autogenerate creates non-nullable columns without a `server_default`, which
fails on tables with rows, so hand-edit those. Every new table must get RLS
enabled on Postgres in its migration (see `f1b3d5e7a9c0_job_runs.py`); the
production self-check logs any public table without it. CI applies all
migrations to an empty database and fails if `alembic check` finds a
difference from the models.

### Rollback

- **API:** Render → the service → Deploys → roll back to the previous deploy.
  If the bad release ran a migration, check whether the old code works with
  the new schema before rolling the database back; downgrades that drop
  columns lose data.
- **Web:** Vercel → Deployments → promote the previous one.
- **App:** a shipped build cannot be recalled. Fix forward with a new build;
  for a severe problem, pause the phased release (App Store) or halt the
  staged rollout (Play).

## Free-tier behaviour

- **Cold starts:** the API sleeps after about 15 minutes without traffic, and
  the next request takes about 50 seconds. The scheduled refresh keeps it
  mostly awake and retries through cold starts. Never enable
  `SCHEDULER_ENABLED` in production: a sleeping process runs no loop.
- **Bandwidth:** Render allows 5 GB a month. The refresh skips rebuilding
  projections when nothing changed, which is what keeps it inside that.
- **Memory:** both optimisers use four CP-SAT workers. If `/dream-team` or
  `/planner` return 502 on the free instance, lower `num_search_workers` to 1
  in `services/transfers.py` and `services/dream_team.py`.
- **Supabase pauses** free projects after about a week without activity; the
  refresh keeps it active.
- **GitHub disables scheduled workflows** after 60 days without repository
  activity; QStash is unaffected.

## Mobile app

### One-time

1. Developer accounts: Apple Developer Program and Google Play Console.
2. The Expo project exists (@and2row/fpl-copilot) and its ID is in
   `app.config.ts`. Under another account, run `npx eas-cli@latest init` and
   set `EAS_PROJECT_ID` (or replace the ID).
3. Confirm the bundle id `com.fplcopilot.app` in `app.config.ts`. It is
   permanent once either store has a build.
4. Credentials: `npx eas-cli@latest credentials` for signing, the APNs key
   (push on iOS) and the FCM v1 service account (push on Android). Add the
   SHA-1 of the EAS and Play App Signing keys to the Google Android OAuth
   client.
5. EAS environment variables for `production` (and `preview`): every
   `EXPO_PUBLIC_*` value, `GOOGLE_IOS_URL_SCHEME`, and for crash reports
   `EXPO_PUBLIC_SENTRY_DSN`, `SENTRY_ORG`, `SENTRY_PROJECT`, and
   `SENTRY_AUTH_TOKEN` as a sensitive variable.
6. Expo project → enhanced push security on, and its access token in
   Render's `EXPO_ACCESS_TOKEN`.

### Each release

```bash
cd mobile
npx eas-cli@latest build --profile production --platform all
```

Then test the build (TestFlight / Play internal testing) against the manual
checks in [TESTING.md](TESTING.md#manual-checks-before-a-release), and submit
when you decide to:

```bash
npx eas-cli@latest submit --platform ios
npx eas-cli@latest submit --platform android
```

`submit` uploads the build; it does not release it. Releasing to users is a
separate button in App Store Connect and Play Console. Use a phased release
(iOS) and a staged rollout (Android). The build number increments
automatically; bump `version` in `app.config.ts` for user-visible releases.

There are no over-the-air updates (`expo-updates` is not installed), so every
change ships as a store build.

## Release checklist

The security items are in [SECURITY.md](../SECURITY.md#before-release-security):
migrations and RLS verification, production secrets, Supabase Auth settings,
RevenueCat Restore Behavior, monitoring. Store-specific requirements (privacy
labels, data safety, review notes, screenshots) belong to the store readiness
checklist.
