# Testing

What is tested, how to run it, and what CI enforces. Every suite runs without
network access or external services except the ones marked otherwise.

## Quick reference

| What | Command (from the folder named) | Needs |
|---|---|---|
| Backend unit and integration | `backend`: `.\test.bat` (Windows) or the pytest line below | dev requirements |
| Backend contract tests | `backend`: `.\test.bat network` | internet (live FPL API) |
| Mobile unit and render | `mobile`: `npm test` | nothing |
| Mobile lint, types, config | `mobile`: `npm run lint`, `npm run typecheck`, `npx expo-doctor` | nothing |
| Web lint, types, build | `frontend`: `npm run lint`, `npm run build`, `npx tsc --noEmit` | nothing |
| End to end | see [Maestro](#end-to-end-maestro) | staging, an e2e build, Maestro |

## Backend

```bash
cd backend
pip install -r requirements-dev.txt        # once, inside the venv
DATABASE_URL="sqlite+aiosqlite:///:memory:" ENVIRONMENT=test pytest -m "not network"
```

On Windows `.\test.bat` sets those variables for you; `.\test.bat -k billing`
passes arguments through. `setup.bat` installs only the runtime requirements,
so install `requirements-dev.txt` once before the first test run.

**How it is set up** (`tests/conftest.py`):

- Each test gets a fresh in-memory SQLite database with every table created.
  The `client` fixture is an HTTP client against the real app with the
  database dependency swapped; `session` is a session on the same database.
- `SCHEDULER_ENABLED`, `JOB_TOKEN` and `CACHE_ENABLED` are forced off so a
  developer's `.env` cannot change outcomes.
- `tests/auth_helpers.py` signs Supabase-shaped tokens (HS256 test secret, or
  an EC key for the JWKS path) for `USER_A` / `USER_B` and connects teams to
  them, so ownership and premium rules are exercised for real.
- Outbound HTTP is replaced per test, usually by patching `httpx.AsyncClient`
  with an `httpx.MockTransport`. Patch with
  `lambda **kw: real(**{**kw, "transport": MockTransport(handler)})`: clients
  pass their own monitored transport, which the mock must replace.

**What guards what:**

| Area | Files | Guards |
|---|---|---|
| Access control | `test_auth.py`, `test_onboarding.py`, `test_security.py` | Token verification edge cases; every `{manager_id}` route enforces ownership, every advice route requires premium, every write route is guarded (structural tests walking all routes via `tests/routes.py`); team-name proof; trial rules and the server clock; production self-checks; body limits; trusted-proxy IPs. The Postgres RLS self-check has no test (SQLite cannot run it). |
| Billing | `test_billing.py` | Webhook auth, signatures, replay window, idempotency, transfers, outages; entitlement precedence; sync. |
| Accounts | `test_account_deletion.py`, `test_push.py` | Deletion order and rollback; what is kept; device registration; push scheduling, dedupe and pruning. |
| Models and optimisers | `test_projection.py`, `test_lineup.py`, `test_transfers.py`, `test_dream_team.py`, `test_planner.py`, `test_chips.py`, `test_confidence.py` | Shrinkage and priors; XI optimality across all formations; FPL constraints on every returned squad; planner tree integrity; chip valuation. |
| Data pipeline | `test_news_parser.py`, `test_news_taxonomy.py`, `test_jobs.py`, `test_squad_state.py`, `test_cache.py`, `test_feedback.py` | Every live news phrasing; price-crossing anti-spam; refresh failure isolation; pending-transfer overrides; what is and is not cached; accuracy scoring. |
| Operations | `test_observability.py`, `test_monitoring.py`, `test_resilience.py` | Log redaction; request IDs; headers; upstream tracking; job runs and heartbeat; what reaches Sentry; Redis reconnection. |
| API surface | `test_api.py`, `test_players.py`, `test_notifications.py` | Routing, validation, empty-database messages; player explorer; Telegram linking. |
| Docs | `test_docs.py` | The API reference matches the routes; every setting is documented; links in the docs resolve. |
| Seed script | `test_e2e_seed.py` | Each persona lands in its state; re-seeding resets it; refuses without the flag or in production. |

**Contract tests** (`test_contract_fpl.py`, marked `network`) assert the shape
of the unofficial FPL API we depend on, including that FPL's own squad rules
still match the optimiser's constants and that every live news string parses.
CI runs them nightly and on every push, without failing the build, so an FPL
change is visible before a user notices it.

**Migrations.** CI applies every migration to an empty SQLite database and
runs `alembic check`, which fails if the models and migrations disagree.

## Mobile

```bash
cd mobile
npm test
```

jest-expo with React Native Testing Library 14. Things that will bite:

- `render`, `fireEvent` and `userEvent` are async in RNTL 14; `await` them.
- `jest.mock` factories may only reference variables whose names start with
  `mock`.
- Give test `QueryClient`s `gcTime: Infinity`, or React Query's garbage
  collection timer keeps Jest running for minutes after the tests finish.
- `EXPO_PUBLIC_*` values are inlined when the file is compiled, so tests
  cannot change them at runtime. Put the decision in a pure function that
  takes the value (see `shouldEnable` in `src/lib/monitoring.ts`).

| Area | Files |
|---|---|
| Logic | `src/lib/__tests__/`: API errors and timeouts, gate decisions, encrypted storage, squad and planner view logic, billing, push, monitoring |
| Screens | `src/__tests__/`: pitch, transfers, player screen, paywall, delete account and notification settings, planner and news, the crash screen. Onboarding and sign-in screens are covered by Maestro, not render tests. |
| Maestro selectors | `src/__tests__/maestro-flows.test.ts` checks that every `id` and literal text in the Maestro flows exists in the app source, so a renamed `testID` fails in seconds |

## Web dashboard

No unit tests. CI runs ESLint, a production build (which type-checks) and
`tsc`, plus an audit of production dependencies. Check UI changes in a browser
against a local backend.

## End to end (Maestro)

Flows in `mobile/.maestro/` cover sign-in and session restore, onboarding,
trial and expiry, the paywall and restore, every main feature, notification
settings, account deletion and offline behaviour. They run against an **e2e
build** pointed at **staging**, after `backend/scripts/e2e_seed.py` resets the
five test personas. Google and Apple sheets cannot be automated, so the e2e
build shows an email sign-in that exists only in that profile and only works
against staging.

Full instructions, personas and a scenario-by-scenario coverage table:
[mobile/.maestro/README.md](../mobile/.maestro/README.md).

`.github/workflows/e2e.yml` runs them on an Android emulator, manually or on a
`v*` tag (about 30–45 minutes, and it changes staging data).

## Manual checks before a release

Things no automated test here can do honestly:

- Real Google and Apple sign-in on devices, including account linking.
- Store purchases with App Store sandbox and Play licence testers: buy, restore
  on a second device, cancel, let a renewal lapse, refund.
- Push delivery on real devices, including tapping through to the right
  screen.
- A forced native crash in a release build reaching Sentry with a readable
  stack trace.

The full release list is in [DEPLOYMENT.md](DEPLOYMENT.md).

## CI

`.github/workflows/ci.yml`, on every push to `main` and every pull request:

| Job | Runs |
|---|---|
| Backend | dependencies, migrations applied and checked, `pytest -m "not network"`, `pip-audit`, contract tests (non-blocking) |
| Frontend | lint, production-dependency audit (high), build, type check |
| Mobile | lint, type check, Jest, `expo-doctor`, production-dependency audit (critical), the e2e-profile guard, a bundle export checked for the test sign-in |
| Secret scan | no committed `.env`; no backend secret names or Sentry auth tokens in `mobile/`; no connection strings with real passwords |

Never mark a failing check as expected or skip it to get green. If a test
fails, the code or the test is wrong; find out which.
