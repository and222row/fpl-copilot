# FPL Copilot

Fantasy Premier League decision support: who to start, who to captain, which
transfers are worth a hit, and when to play chips, with every recommendation
explained by the numbers behind it. An iOS and Android app with a web
dashboard, on a FastAPI backend.

The advice comes from a transparent projection model and exact optimisers,
not a language model: every number traces back to FPL data, and the solvers
say when an answer is proven optimal.

## What is in this repository

| Folder | What | Stack |
|---|---|---|
| `backend/` | API, projection model, optimisers, scheduled refresh, accounts and billing | Python 3.12, FastAPI, SQLAlchemy (async), Alembic, OR-Tools |
| `mobile/` | The iOS and Android app | Expo SDK 57, React Native, Expo Router, TanStack Query |
| `frontend/` | Web dashboard for signed-in users | Next.js 16, React 19, Tailwind |
| `docs/` | Developer documentation | |

Hosted on free tiers: Render (API), Vercel (web), Supabase (Postgres and
Auth), Upstash (Redis and QStash), RevenueCat (billing), Sentry and
Healthchecks.io (monitoring).

## Quick start

You need Python 3.12 (3.14 is too new: `asyncpg` and `pydantic-core` have no
wheels for it), Node.js 22, and either Docker or free Supabase and Upstash
accounts.

### 1. Database and Redis

Locally, with Docker:

```bash
docker compose up -d postgres redis
```

That matches the backend's default `DATABASE_URL` and `REDIS_URL`, so delete
those two lines from `backend/.env` after copying it in the next step.

Without Docker, create a free Supabase project (Settings → Database → URI,
with the scheme changed to `postgresql+asyncpg://`) and a free Upstash Redis
database, and put their URLs in `backend/.env`.

### 2. Backend

Windows:

```bash
cd backend
copy .env.example .env
.\setup.bat
```

macOS and Linux:

```bash
cd backend
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Then, with the virtual environment active, create the tables and start the
API:

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

(`.\start.bat` does the second line on Windows.) Check
http://localhost:8000/api/v1/health returns `"status": "ok"`; the interactive
API docs are at http://localhost:8000/api/docs.

### 3. Load FPL data (the worker)

There is no separate worker process. All background work is one refresh job,
triggered over HTTP. Locally, with `JOB_TOKEN` empty, it needs no token:

```bash
curl -X POST "http://localhost:8000/api/v1/jobs/refresh"
```

It pulls players and fixtures from the live FPL API, builds projections and
raises alerts; the first run takes a minute or two. To keep data fresh while
you work, set `SCHEDULER_ENABLED=true` in `backend/.env` and restart the API;
it then refreshes every `REFRESH_INTERVAL_MINUTES`.

With `AUTH_REQUIRED=false` (the local default) you can call team endpoints
from the API docs without signing in, e.g. `GET /api/v1/decisions/{your FPL
team id}`.

### 4. Web dashboard

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000. The dashboard requires sign-in, so it needs a
Supabase project with Apple or Google configured
([docs/AUTHENTICATION.md](docs/AUTHENTICATION.md#setup-checklist)) and its URL
and publishable key in `.env.local`. If you run on another port, add that
origin to `CORS_ORIGINS` in `backend/.env` and to Supabase's redirect URLs.

### 5. Mobile app

The app needs a development build (Expo Go lacks its native modules):

```bash
cd mobile
npm install
cp .env.example .env
npx expo run:android
```

Point `EXPO_PUBLIC_API_URL` at your computer's LAN IP, or `10.0.2.2` from the
Android emulator. Full instructions: [docs/MOBILE_APP.md](docs/MOBILE_APP.md#running-it-locally).

### 6. Tests

Install the backend test dependencies once inside the virtual environment
(`setup.bat` installs only the runtime ones):

```bash
pip install -r requirements-dev.txt
```

Then:

```bash
cd backend && .\test.bat
```

```bash
cd mobile && npm test
```

On macOS and Linux run the backend tests with
`DATABASE_URL="sqlite+aiosqlite:///:memory:" ENVIRONMENT=test pytest -m "not network"`.
Everything else, including Maestro end-to-end tests: [docs/TESTING.md](docs/TESTING.md).

## Documentation

| Document | Covers |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, request flow, the refresh pipeline, data model, design decisions |
| [AUTHENTICATION.md](docs/AUTHENTICATION.md) | Sign-in, token verification, authorisation, FPL team ownership, account deletion |
| [PAYMENTS.md](docs/PAYMENTS.md) | Store billing via RevenueCat, the trial, entitlements, the webhook |
| [MOBILE_APP.md](docs/MOBILE_APP.md) | The Expo app: features, structure, running, builds |
| [API.md](docs/API.md) | Conventions, errors, rate limits, and every route with its access level |
| [TESTING.md](docs/TESTING.md) | Suites, how to run them, CI, manual release checks |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | First deploy, routine deploys, migrations, rollback, app releases |
| [ENVIRONMENT_VARIABLES.md](docs/ENVIRONMENT_VARIABLES.md) | Every setting, where it is read and where it is set |
| [OBSERVABILITY.md](docs/OBSERVABILITY.md) | Logging, error and crash tracking, job and webhook monitoring, runbook |
| [SECURITY.md](SECURITY.md) | Security review findings, OWASP mapping, release checklist |
| [DESIGN_NOTES.md](docs/DESIGN_NOTES.md) | Why the model, optimisers and pipeline work as they do |

## Status

The backend, web dashboard and mobile app are feature complete for a first
release and covered by automated tests. Not yet done before launch: running
the pending migrations and production configuration, real-device testing of
sign-in, purchases and push, store listings, and the web page Google Play
requires for account deletion requests. See
[DEPLOYMENT.md](docs/DEPLOYMENT.md) and the release checklist in
[SECURITY.md](SECURITY.md#before-release-security).
