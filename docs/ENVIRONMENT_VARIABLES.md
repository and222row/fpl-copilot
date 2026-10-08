# Environment variables

Every setting, where it is read, and where it is set. Templates with comments
live next to each app: `backend/.env.example`, `frontend/.env.example`,
`mobile/.env.example`. Copy them to `.env` (`.env.local` for the frontend);
those files are git-ignored and CI fails if one is committed.

**The one rule:** anything prefixed `NEXT_PUBLIC_` or `EXPO_PUBLIC_` is compiled
into a bundle that anyone can download and read. Only public values go there.
CI greps `mobile/` for backend secret names and fails if it finds one.

`tests/test_docs.py` checks that every backend setting and every public
frontend/mobile variable used in code appears in this file.

## Backend (FastAPI)

Read by `backend/app/config.py` (pydantic-settings) from the process
environment, falling back to `backend/.env`. Names are case-insensitive.
Production values live in Render's dashboard; `render.yaml` lists them, with
`sync: false` for secrets so they are never in git.

### Core

| Variable | Default | Secret | Purpose |
|---|---|---|---|
| `ENVIRONMENT` | `development` | | `development`, `test`, `staging` or `production`. Production turns on the startup self-checks, fails closed on missing secrets, and hides the API docs. Development gives human-readable logs and no rate limits. |
| `DATABASE_URL` | local Postgres from `docker-compose.yml` | yes | `postgresql+asyncpg://...`. For Supabase, take Settings → Database → URI and change the scheme to `postgresql+asyncpg://`. Tests use `sqlite+aiosqlite:///:memory:`. |
| `REDIS_URL` | `redis://localhost:6379/0` | yes | Upstash gives `rediss://...`. Only used as a cache, which fails open. |
| `CORS_ORIGINS` | `http://localhost:3000` | | Comma-separated web origins allowed to call the API. Add `http://localhost:3001` when the frontend runs there. The mobile app is not a browser and needs no entry. |
| `SQL_ECHO` | `false` | | Log every SQL statement. |
| `TRUSTED_PROXY_HOPS` | `0` | | Proxies in front of the API that append to `X-Forwarded-For`. `1` on Render; `0` locally. Decides the client IP for rate limits. |
| `MAX_REQUEST_BYTES` | `1000000` | | Larger request bodies are refused with 413. |

### Authentication (Supabase)

| Variable | Default | Secret | Purpose |
|---|---|---|---|
| `SUPABASE_URL` | empty | | Project URL. Tokens are verified against its JWKS and issuer. Empty rejects every token. |
| `SUPABASE_JWT_SECRET` | empty | yes | Only for projects still on the legacy shared HS256 secret. Leave empty with asymmetric signing keys. |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | | Expected `aud`. Rejects the anon and service keys, which are not user tokens. |
| `SUPABASE_SERVICE_KEY` | empty | yes | Secret key (`sb_secret_...`) or legacy service_role key. Used only to delete a user's sign-in identity on account deletion, and by the e2e seed script. |
| `AUTH_REQUIRED` | `false` | | `true` in production: team routes and premium features refuse anonymous calls. `false` only for poking at the API locally. |

### Scheduled refresh

| Variable | Default | Secret | Purpose |
|---|---|---|---|
| `JOB_TOKEN` | empty | yes | Required in `X-Job-Token` for operator endpoints. Empty leaves them open outside production and closed (503) in production. Must match the GitHub secret and the QStash schedule. |
| `SCHEDULER_ENABLED` | `false` | | Run the refresh in-process. Local only: a sleeping free-tier instance runs no loop. |
| `REFRESH_INTERVAL_MINUTES` | `30` | | Interval for the in-process scheduler (floor 5 minutes). |
| `CACHE_ENABLED` | `true` | | Redis cache for per-manager FPL reads. |
| `FPL_CACHE_TTL_SECONDS` | `90` | | Cache lifetime; short because picks responses carry live points. |

### Billing (RevenueCat)

| Variable | Default | Secret | Purpose |
|---|---|---|---|
| `REVENUECAT_SECRET_KEY` | empty | yes | Secret v1 API key (`sk_...`). Lets the server read a customer's real subscription state. Never in the app. |
| `REVENUECAT_WEBHOOK_AUTH` | empty | yes | The exact `Authorization` header value configured on the webhook. Empty disables the webhook (503). |
| `REVENUECAT_WEBHOOK_SIGNING_SECRET` | empty | yes | Webhook signing secret. Required in production; deliveries must then carry a valid signature under five minutes old. |
| `REVENUECAT_ENTITLEMENT_ID` | `pro` | | Entitlement identifier in RevenueCat. |
| `REVENUECAT_API_BASE` | `https://api.revenuecat.com/v1` | | Override only for testing. |

### Notifications

| Variable | Default | Secret | Purpose |
|---|---|---|---|
| `EXPO_ACCESS_TOKEN` | empty | yes | Expo access token for push, with "enhanced push security" enabled in the Expo project so a leaked device token cannot be pushed to by anyone else. Push works without it, less securely. |
| `TELEGRAM_BOT_TOKEN` | empty | yes | From @BotFather. Empty disables Telegram alerts. |
| `TELEGRAM_WEBHOOK_SECRET` | empty | yes | Echoed by Telegram on every update; `scripts/telegram_setup.py set-webhook` generates one. |
| `TELEGRAM_MIN_SEVERITIES` | `critical,warning` | | Which alert severities are sent to Telegram. |

### Monitoring

| Variable | Default | Secret | Purpose |
|---|---|---|---|
| `SENTRY_DSN` | empty | semi | Sentry project DSN. Empty disables error tracking. See [OBSERVABILITY.md](OBSERVABILITY.md). |
| `SENTRY_TRACES_SAMPLE_RATE` | `0` | | Share of requests traced. Keep 0 on the free plan. |
| `RELEASE` | `RENDER_GIT_COMMIT` | | Tags errors with the deployed commit. Render sets `RENDER_GIT_COMMIT` itself. |
| `HEALTHCHECKS_PING_URL` | empty | semi | Healthchecks.io ping URL for the refresh heartbeat. |

### Reserved

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | empty | Not used. Kept from the original blueprint; news parsing turned out to need no LLM. |
| `API_FOOTBALL_KEY` | empty | Not used. Reserved for a second football data source. |

### Backend scripts only

Read from `backend/.env` or the shell by the scripts in `backend/scripts/`,
never by the API.

| Variable | Script | Purpose |
|---|---|---|
| `QSTASH_TOKEN` | `qstash_schedule.py` | Upstash console → QStash token. |
| `API_BASE_URL` | `qstash_schedule.py`, `telegram_setup.py` | Public API URL the schedule and webhook point at. |
| `E2E_ALLOW_SEED` | `e2e_seed.py` | Must be `1`, together with `ENVIRONMENT` `staging` or `development`, or the seed refuses to run. |
| `E2E_PASSWORD` | `e2e_seed.py` | Password for the test personas (12+ characters), staging only. |
| `E2E_FPL_TEAM_IDS` | `e2e_seed.py` | Four real public FPL team IDs, comma-separated. |

## Web dashboard (Next.js)

Set in `frontend/.env.local` locally and in Vercel → Project → Settings →
Environment Variables. All are public. They are inlined at build time, so a
change needs a redeploy.

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend origin, no trailing slash. Also added to the page's CSP `connect-src`. |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL (same project as the app). Also added to `connect-src`. |
| `NEXT_PUBLIC_SUPABASE_KEY` | Supabase **publishable** key. |

## Mobile app (Expo)

`EXPO_PUBLIC_*` values are inlined into the JavaScript bundle at build time.
Set them in `mobile/.env` for local builds and in the EAS environment
(`development`, `preview`, `production`) for cloud builds. The others are read
by `app.config.ts` at build time and do not reach the bundle.

| Variable | Public | Purpose |
|---|---|---|
| `EXPO_PUBLIC_API_URL` | yes | Backend origin. Release builds refuse anything but https. Required. |
| `EXPO_PUBLIC_SUPABASE_URL` | yes | Supabase project URL. Required. |
| `EXPO_PUBLIC_SUPABASE_KEY` | yes | Supabase publishable key. Required. |
| `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID` | yes | Google OAuth web client ID; Supabase checks the ID token's audience against it. |
| `EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID` | yes | Google OAuth iOS client ID. |
| `EXPO_PUBLIC_REVENUECAT_IOS_KEY` | yes | RevenueCat public SDK key (`appl_...`). |
| `EXPO_PUBLIC_REVENUECAT_ANDROID_KEY` | yes | RevenueCat public SDK key (`goog_...`). |
| `EXPO_PUBLIC_TERMS_URL` | yes | Terms of service page, linked from the paywall and Profile. |
| `EXPO_PUBLIC_PRIVACY_URL` | yes | Privacy policy page, linked from the paywall and Profile. |
| `EXPO_PUBLIC_SENTRY_DSN` | yes | Sentry React Native DSN. Empty disables crash reporting. |
| `EXPO_PUBLIC_E2E` | yes | `true` only in the `e2e` EAS profile: shows the email sign-in used by Maestro. CI fails if any other profile sets it; production pins `false`. |
| `GOOGLE_IOS_URL_SCHEME` | no | The reversed iOS client ID, for the Google sign-in config plugin. |
| `EAS_PROJECT_ID` | no | Overrides the EAS project ID in `app.config.ts` (@and2row/fpl-copilot), e.g. to build under another Expo account. Push tokens are issued per EAS project. |
| `SENTRY_ORG`, `SENTRY_PROJECT` | no | Turn on source map and debug symbol upload in EAS builds. |
| `SENTRY_URL` | no | Sentry host for uploads; defaults to `https://sentry.io/`. |
| `SENTRY_AUTH_TOKEN` | no, **secret** | Sentry organisation token for the upload. EAS environment only, as a sensitive variable. Never in `.env` or an `EXPO_PUBLIC_` name. |
| `EAS_BUILD_PROFILE` | no | Set by EAS; tags crash reports with the build profile. |

## GitHub Actions

Repository → Settings → Secrets and variables → Actions.

| Name | Kind | Used by | Purpose |
|---|---|---|---|
| `API_BASE_URL` | secret | `refresh.yml` | Production API URL for the backup scheduler. |
| `JOB_TOKEN` | secret | `refresh.yml` | Byte-identical to the backend's `JOB_TOKEN`. |

The `staging` environment (used by `e2e.yml`) holds staging values only. Never
add production credentials there.

| Name | Kind | Purpose |
|---|---|---|
| `STAGING_DATABASE_URL` | secret | Staging database, for the seed script. |
| `STAGING_SUPABASE_SERVICE_KEY` | secret | Staging Supabase secret key, for the seed script. |
| `E2E_PASSWORD` | secret | Test persona password. |
| `STAGING_API_URL` | variable | Staging API URL baked into the e2e build. |
| `STAGING_SUPABASE_URL` | variable | Staging Supabase URL. |
| `STAGING_SUPABASE_PUBLISHABLE_KEY` | variable | Staging publishable key. |
| `STAGING_REVENUECAT_ANDROID_KEY` | variable | Staging RevenueCat public key. |
| `E2E_FPL_TEAM_IDS` | variable | Four FPL team IDs for the personas. |
| `E2E_NEW_TEAM_ID` | variable | A fifth team ID nobody has connected. |
| `TERMS_URL`, `PRIVACY_URL` | variable | Legal links for the e2e build. |
