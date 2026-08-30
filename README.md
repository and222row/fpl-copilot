# FPL Copilot

AI-Powered Fantasy Premier League Decision Platform.

## Prerequisites

- Python 3.12+
- Node.js 20+
- A free Supabase account (PostgreSQL)
- A free Upstash account (Redis)

## First-time setup

### 1. Create your cloud services (both free)

**Supabase (PostgreSQL)**
1. Go to supabase.com → New project
2. Settings → Database → Connection string → URI
3. Copy the URI (starts with `postgresql://...`)

**Upstash (Redis)**
1. Go to upstash.com → Create database → choose a region
2. Copy the REDIS_URL from the Details tab (starts with `rediss://...`)

### 2. Configure environment variables

```bash
cd backend
copy .env.example .env
```

Open `backend\.env` and paste your Supabase and Upstash URLs.

### 3. Set up and start the backend

```bash
cd backend
.\setup.bat       # creates venv + installs packages (first time only)
.\start.bat       # starts the API server
```

### 4. Verify the backend is healthy

Open: http://localhost:8000/api/v1/health

Expected:
```json
{"status": "ok", "database": "ok", "redis": "ok"}
```

API docs: http://localhost:8000/api/docs

### 5. Set up and start the frontend

In a new terminal:

```bash
cd C:\Users\andrew.bekhiet\FPL
npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --no-turbopack
cd frontend
npm run dev
```

Open: http://localhost:3000

## Project structure

```
FPL/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, CORS, lifespan
│   │   ├── config.py        # Settings from .env
│   │   ├── database.py      # Async PostgreSQL (SQLAlchemy)
│   │   ├── redis_client.py  # Async Redis
│   │   ├── models/          # ORM models (added in Phase 2)
│   │   └── routers/
│   │       └── health.py    # GET /api/v1/health
│   ├── alembic/             # Database migrations
│   ├── setup.bat            # First-time: creates venv + pip install
│   ├── start.bat            # Daily: starts uvicorn
│   └── .env                 # Your secrets (never committed)
└── frontend/                # Next.js app (created in step 5)
```

## Daily development

```bash
# Terminal 1 — backend
cd backend
.\start.bat

# Terminal 2 — frontend
cd frontend
npm run dev
```

## API endpoints

Interactive docs: http://localhost:8000/api/docs

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | DB + Redis connectivity |
| POST | `/api/v1/fpl/sync/bootstrap` | Pull teams, gameweeks, players from FPL |
| POST | `/api/v1/fpl/sync/fixtures` | Pull all season fixtures |
| GET | `/api/v1/fpl/gameweek` | Active gameweek (current, else next) |
| GET | `/api/v1/fpl/players` | Filter/sort players (`position`, `max_price`, `sort_by`, `limit`) |
| GET | `/api/v1/fpl/players/{id}` | Full player detail |
| GET | `/api/v1/fpl/teams` | All 20 teams with strength ratings |
| GET | `/api/v1/fpl/fixtures` | Fixtures (`gameweek`, `team_id`) |
| GET | `/api/v1/fpl/manager/{id}` | Manager profile from FPL |
| GET | `/api/v1/fpl/manager/{id}/squad` | 15-player squad, enriched |
| GET | `/api/v1/fpl/manager/{id}/squad-state` | Which squad we believe you hold, and its source |
| POST | `/api/v1/fpl/manager/{id}/squad-state/transfers` | Record transfers you already made |
| DELETE | `/api/v1/fpl/manager/{id}/squad-state` | Discard the override |
| POST | `/api/v1/projections/rebuild/team-strength` | Recompute custom FDR from results |
| POST | `/api/v1/projections/rebuild` | Rebuild xPts projections (`horizon`) |
| GET | `/api/v1/projections` | Top projected players for a GW |
| GET | `/api/v1/projections/player/{id}` | Full component breakdown per GW |
| GET | `/api/v1/projections/team-strength` | Derived attack/defence ratings |
| POST | `/api/v1/projections/backtest/ingest-history` | Pull per-GW actuals |
| GET | `/api/v1/projections/backtest` | Score projections vs actuals |
| GET | `/api/v1/decisions/{manager_id}` | Everything: lineup, captain, issues, transfer |
| GET | `/api/v1/decisions/{manager_id}/lineup` | Optimal XI, bench order, captain |
| GET | `/api/v1/decisions/{manager_id}/captain` | Captain ranking in all 3 risk modes |
| GET | `/api/v1/decisions/{manager_id}/transfers` | Best transfers vs rolling |
| POST | `/api/v1/news/detect` | Diff against last sync, log availability changes |
| GET | `/api/v1/news/events` | Chronological change feed with evidence |
| POST | `/api/v1/news/alerts/{manager_id}/generate` | Raise alerts for owned players |
| GET | `/api/v1/news/alerts/{manager_id}` | This manager's alerts |
| GET | `/api/v1/news/price-watch` | Players near a price change |
| GET | `/api/v1/news/parse-check` | Admin: how the parser reads every news string |
| GET | `/api/v1/feedback/{manager_id}/accuracy` | Running accuracy per decision category |
| GET | `/api/v1/feedback/{manager_id}/history` | Per-gameweek outcomes |
| GET | `/api/v1/feedback/{manager_id}/pending` | Advice saved but not yet graded |
| POST | `/api/v1/feedback/{manager_id}/score` | Grade one finished gameweek |
| POST | `/api/v1/feedback/{manager_id}/score-all` | Grade everything outstanding |
| GET | `/api/v1/planner/{manager_id}` | Multi-GW transfer plan as a decision tree |
| GET | `/api/v1/dream-team` | Best legal 15 from the whole pool, with reasons |
| POST | `/api/v1/jobs/refresh` | Full refresh: sync, detect, rebuild, alert |
| GET | `/api/v1/jobs/status` | Scheduler state and tracked managers |
| POST | `/api/v1/jobs/track/{manager_id}` | Register a team for background alerts |

### Rebuild order

Dependencies run one way — running these out of order gives silently wrong numbers:

```
sync/bootstrap -> sync/fixtures -> news/detect -> rebuild/team-strength -> rebuild
  (players,         (results)      (changes vs     (custom FDR)            (xPts)
   scoring rules)                   last sync)
```

The dashboard's **Sync FPL data** button runs all four in order.

## Database migrations

After changing anything in `backend/app/models/`:

```bash
cd backend
.\migrate.bat "what you changed"
```

That generates the migration and applies it. To apply existing migrations only:

```bash
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## The projection model

`proj-v1` is a transparent statistical model, not ML — every number traces to an
input, so it can be debugged and gives the backtest something to beat.

Per player per gameweek: availability → expected minutes → fixture context →
scoring components (appearance, goals, assists, clean sheet, goals conceded,
saves, defensive contribution, bonus, cards, penalties) → xPts + variance.

Three design decisions worth knowing about:

**Scoring rules are synced, not hardcoded.** FPL publishes them at
`bootstrap-static → game_config.scoring`; they land in the `scoring_rules`
table. A rules change is a sync, not a deploy. (GK goals are worth **10** in
2026/27, and defensive contribution pays 2 — both easy to get wrong from memory.)

**Priors scale with price.** FPL price is the market's aggregate judgement of a
player's output and it is the strongest prior available. Without it, a £4.5m
defender who scores once in 77 minutes gets an xG/90 of 1.7 from a single shot
and outranks Haaland. A rate is also capped at `MAX_RATE_VS_PRIOR` (3x) of what
price implies.

**`finished_provisional`, not `finished`.** FPL has three fixture states:
`started`, `finished_provisional` (match over, bonus pending) and `finished`
(data verified, can lag days). Anything asking "has this been played?" must use
`finished_provisional` — reading `finished` makes a fully-played gameweek look
like it never happened.

### Backtesting

```bash
curl -X POST "http://localhost:8000/api/v1/projections/backtest/ingest-history?limit=200"
```
```bash
curl "http://localhost:8000/api/v1/projections/backtest?min_expected_minutes=60"
```

Read `spearman` (rank correlation) before `mae` — FPL decisions are comparisons
between players, not absolute forecasts. Check the `caveats` field: it flags
sample-selection bias and gameweeks where the projection saw the result it was
predicting.

## The decision engine

**Starting XI, bench and captain** are solved exactly by enumeration — there are
only eight legal formations, so brute force is both provably optimal and faster
than a solver. See [lineup.py](backend/app/services/lineup.py).

**Transfers** use OR-Tools CP-SAT, which needs to reason about squad
composition, the 3-per-club cap and the budget *jointly* — greedy swaps get this
wrong. The points hit sits inside the objective, so a −4 is only proposed when
it pays for itself across the horizon. Holding is always priced as an explicit
alternative rather than assumed worse.

Captaincy has three modes: `safe` penalises variance and rotation risk,
`balanced` maximises expected points, `differential` rewards low ownership.
The vice is chosen for reliability from a different club to the captain.

**Confidence is computed, not asserted** — from data freshness, minutes
certainty, model precision, decision margin and sample depth, each returned
with its weight so a low score can be explained. See
[confidence.py](backend/app/services/confidence.py).

## News and availability — no LLM, no cost

The blueprint assumed an LLM would be needed to extract availability from
unstructured news. It is not, because **FPL's `player.news` field is strictly
formulaic**:

```
"Hamstring injury - 75% chance of playing"
"Ankle injury - Expected back 14 Sep"
"Knee injury - Unknown return date"
"Has joined Como permanently"
```

[news_parser.py](backend/app/services/news_parser.py) handles all of it with
regex — **100% parse rate across all 118 live strings**. An LLM re-deriving
what FPL already states would be slower, cost money, and be less reliable.

### The bug this exposed

`chance_of_playing_this_round` is per-round, so it goes **null or stale between
gameweeks** — while the news text stays current. Reading the field first was
under-projecting every doubtful player:

| Player | `chance` field | News text | Was using | Now uses |
|---|---|---|---|---|
| Pedro Porro | `0%` | 75% | 0.0 | 0.75 |
| Van de Ven | `0%` | 50% | 0.0 | 0.50 |
| Kudus | `25%` | 50% | 0.25 | 0.50 |
| Ajayi | `null` | 75% | 0.55 *(status default)* | 0.75 |

14 players were affected. `resolve_availability` now prefers the news text,
with hard statuses (injured/suspended) still overriding everything — FPL
sometimes leaves a stale "75% chance" string on a player it has since ruled out.

### Where an LLM would still help

Only for genuinely unstructured sources that arrive *before* FPL updates —
club press conferences, journalist posts. That is optional and not built. If
you want it later, Google Gemini's free tier or a local Ollama model would both
work; the parser interface is the seam to plug into.

## Tests

```bash
cd backend
.\test.bat            # 231 unit + integration, ~3s, no network
.\test.bat network    # 15 contract tests against the live FPL API
.\test.bat all        # everything
.\test.bat -k parser  # any pytest args pass through
```

| Suite | Count | Guards |
|---|---|---|
| `test_projection.py` | 44 | Shrinkage, Poisson helpers, expected minutes, custom FDR |
| `test_news_parser.py` | 43 | Every live news phrasing, availability precedence |
| `test_api.py` | 42 | Routing, query validation, empty-DB error messages |
| `test_observability.py` | 34 | Secret redaction, request IDs, security headers |
| `test_lineup.py` | 27 | XI optimality, formation legality, bench order, captaincy |
| `test_transfers.py` | 19 | FPL constraint satisfaction on the returned squad |
| `test_confidence.py` | 16 | Each factor moves the score in the right direction |
| `test_feedback.py` | 33 | Accuracy scoring: error vs regret vs override |
| `test_planner.py` | 30 | Free-transfer rollover, tree integrity, horizon truncation |
| `test_jobs.py` | 22 | Price-crossing anti-spam, job auth, failure isolation |
| `test_squad_state.py` | 37 | Override precedence, bank arithmetic, expiry, sold-player alerts, squad display |
| `test_dream_team.py` | 55 | Squad legality, two-tier objective, reason generation |
| `test_contract_fpl.py` | 15 | Live FPL response shape (network-marked) |
| `test_resilience.py` | 6 | Redis reconnection after a dropped connection |

Most of the suite is pure functions with no database, which is why it runs in
three seconds. API tests use in-memory SQLite via dependency override, so no
external service is needed.

### Why the contract tests matter

The FPL endpoints are unofficial and can change without notice. Rather than
discovering that through wrong projections, these assert the shape we depend
on — including that FPL's own squad rules still match the optimizer's
constants, and that every live news string still parses. CI runs them nightly.

### Verifying the optimizer

An optimizer that silently breaks a rule is worse than none, so the transfer
tests assert constraints on the *returned squad*, not just that a solution came
back: squad size, position counts, club cap, budget, hit arithmetic, net-gain
arithmetic, and that the chosen XI is the true optimum across all formations.

## Production hardening

**Structured logging.** JSON in production, human-readable in development, with
recursive redaction of anything credential-shaped — a log aggregator is where
secrets go to live forever, and `extra={...}` makes it easy to pass a whole
settings object by accident.

**Request correlation.** Every response carries `X-Request-ID` (echoed if you
supply one) and `X-Response-Time-ms`. Error responses include the ID so an
opaque 500 can be traced to its traceback.

**Rate limits**, per-IP, in three named tiers:

| Tier | Limit | Applies to |
|---|---|---|
| `HEAVY` | 6/min | Solver runs, projection rebuilds, history ingest |
| `UPSTREAM` | 30/min | Anything fanning out to the unofficial FPL API |
| `READ` | 120/min | Served from our own database |

Disabled in development and test so they don't trip during normal work.

**Security headers** — `nosniff`, `DENY` framing, no referrer, plus HSTS
outside development. CORS is narrowed to the methods and headers actually used.

**Redis reconnection.** Managed providers drop idle connections — Upstash's
free tier does so within minutes, which showed up as a degraded health check on
an otherwise healthy service. The client now pings idle pooled connections
before reuse, retries with backoff, and rebuilds the pool once if a command
still fails.

**Data freshness** at `GET /api/v1/health/freshness`: per-dataset age and
status, row counts, and matches played (which explains early-season low
confidence).

## A hard limit: we cannot see your pending transfers

**FPL's public API does not expose transfers made for a gameweek that has not
started.** Verified against the live API:

```
/entry/{id}/event/{next_gw}/picks/   404   the gameweek has not started
/entry/{id}/transfers/               []    pending moves are omitted
/my-team/{id}/                       403   needs the manager's own login
```

So the freshest squad available is the one **locked at the last deadline**. The
moment you transfer, every recommendation is about a squad you no longer own —
and the optimiser will happily re-suggest a move you already made.

This is not fixable by reading a different endpoint; the data is not published.
What the app does instead:

1. **Never presents a stale squad as current.** `squad_state` reports
   `squad_source` (`fpl_api` or `manager_override`) and a `stale_warning`
   whenever the squad predates the target gameweek.
2. **Lets you correct it.** Record the transfers you made and the advice runs
   against your real squad, with bank and free transfers adjusted to match.
3. **Expires the correction.** An override is discarded once its gameweek
   starts, because FPL becomes authoritative again — a stale override that
   looks authoritative would be worse than no override at all.

```bash
curl -X POST "http://localhost:8000/api/v1/fpl/manager/{id}/squad-state/transfers"   -H "Content-Type: application/json"   -d '{"moves":[{"out":1,"in":572}]}'
```

Player headshots come from FPL's CDN at
`resources.premierleague.com/.../110x140/p{code}.png`, using the `code` field
(not `photo`). Roughly one player in eight has no image and returns 403, so the
card falls back to a position badge on `onError` rather than showing a break.

A player brought in by a recorded transfer keeps the slot of whoever he
replaced, is labelled `Raya → Tzolakis` on the card, and never inherits the
captain's armband — copying the pick wholesale would hand it to him.

Everything that reads a squad goes through `resolve_squad` — recommendations,
the planner, and alert generation. Reading FPL picks directly anywhere would
reintroduce the bug: alerts were once raised for players the manager had already
sold, because the alert job bypassed it.

Alerts about players no longer in the squad are hidden by default
(`still_owned: false`, pass `include_sold=true` to see them). An alert is meant
to be actionable, and "the player you sold is about to rise" reads as a mistake
even though it was true when raised.

Selling price is assumed to equal current price: FPL's 50% sell-on fee needs the
purchase price, which the public API also does not expose. For a squad held since
the season started they are the same.

## Which gameweek does advice target?

Every recommendation targets **the next gameweek with an open deadline** — not
the one currently being played. Once a deadline passes the squad is locked, so
advice about that gameweek describes a transfer the manager can no longer make.

Two different gameweeks are therefore in play at once, and conflating them is
the bug this guards against:

| | Which gameweek | Why |
|---|---|---|
| **Target** | next with an open deadline | the decision you can still take |
| **Squad source** | latest that has started | FPL only exposes picks once a gameweek begins |

Mid-season those differ: with GW1 played and GW2's deadline ahead, advice targets
GW2 while the squad is read from GW1. `GET /api/v1/fpl/gameweek` returns the
target plus `current_gameweek` and `deadline_passed`, so the UI can say
*"Planning Gameweek 2 · GW1 in progress"* rather than showing a deadline that has
already gone.

Shared helpers in [fpl_sync.py](backend/app/services/fpl_sync.py):
`get_next_open_gameweek`, `get_latest_started_gameweek`, `deadline_has_passed`.

## Background refresh and alerts

Alerts are only useful if they arrive without being asked for. Two triggers run
the **same** job, so behaviour is identical either way:

```bash
POST /api/v1/jobs/refresh
```

```
bootstrap -> fixtures -> detect changes -> team strength -> projections -> alerts
```

Each step is isolated: a transient FPL failure is recorded and the remaining
stages still run, rather than leaving everything stale.

### Choosing a trigger

**In-process scheduler** — set `SCHEDULER_ENABLED=true` and
`REFRESH_INTERVAL_MINUTES=30`. Works wherever the process stays alive, so it is
the right choice locally. Requires a restart, since uvicorn's reloader watches
`.py` files and not `.env`.

**External cron** — [`.github/workflows/refresh.yml`](.github/workflows/refresh.yml)
calls the endpoint every 30 minutes. Necessary on a free tier that sleeps after
inactivity, because an in-process loop dies with the process. Add `API_BASE_URL`
and `JOB_TOKEN` as repository secrets; without them the workflow skips rather
than failing.

The interval has a hard floor of 5 minutes: a refresh takes over a minute, and
hammering the unofficial FPL endpoints risks getting the app blocked.

### Securing it

A refresh rewrites thousands of rows and makes hundreds of upstream calls, so it
must not be publicly triggerable. Set `JOB_TOKEN` and callers must send
`X-Job-Token`, compared with `secrets.compare_digest`. Unset means open, which is
fine locally — **set it before exposing the API**.

### Who gets alerts

There are no accounts, so a team ID is registered in `tracked_managers` the first
time its squad is loaded. The job then generates alerts for each tracked manager,
and one unreachable team ID does not stop the others.

## Pre-emptive price warnings

FPL publishes progress toward its own price-change threshold, so warning
*before* a change needs no modelling — only a crossing check:

```
João Pedro price likely to rise soon
Price rise likely: 77% of the way to FPL's threshold (+165,252 net transfers)
```

**The crossing is what matters, not the level.** The percentage creeps upward
continuously, so alerting whenever it sits above the line would resend the same
warning every 30 minutes until the price moved. `PlayerAvailabilitySnapshot`
stores the previous percentage so only the transition fires — and a player who
drops back and approaches again correctly warns twice.

Two thresholds, deliberately different:

| | Threshold | Meaning |
|---|---|---|
| Price Watch list | 50% | "drifting — worth monitoring" |
| Alert | 75% | "likely tonight — act now" |

Once a price has actually moved, the `price_change` event takes precedence:
report the move, not a prediction of it.

## Best possible squad

Answers "if I wildcarded right now, what would I pick?" — the strongest legal 15
from the whole pool, ignoring what you own.

```bash
curl "http://localhost:8000/api/v1/dream-team?budget=100&horizon=1"
```

### Why it needs its own solver

The transfer optimiser starts from a squad and caps how many players may
change. Here nothing is owned and the whole budget is in play — but the real
difference is the objective.

**Only the XI scores.** A solver maximising the sum of all 15 spends real money
on a bench that never plays. So squad membership, XI selection and the
captaincy are three linked decisions in one model:

```
squad[p]    in the 15?
start[p]    in the XI?        (start <= squad)
captain[p]  wears the armband? (captain <= start)
```

The objective pays the XI in full, the bench at `BENCH_WEIGHT` (0.12), and adds
the captain's points again because the armband doubles them. That produces the
shape a competent manager actually builds — on live data, **£83m in the XI and
£17m on a deliberately cheap bench**.

### The reasons are numbers, not prose

No LLM is involved. Each reason is derived from a figure the model produced, so
every claim is checkable:

```
Captain: highest projected return in the XI at 6.7 pts, doubled to 13.3
Top-projected FWD in the game (6.7 pts)
Points come mainly from goal threat (3.4 of 6.7 next GW)
Average away fixture, FDR 2.9
First-choice penalty taker
```

Risk is surfaced too — rotation doubt below 70% start probability, and an
imminent price change either way.

### Optimality is claimed only when proven

CP-SAT returns `FEASIBLE` when it found a good squad but ran out of time proving
none better exists. The response carries `proven_optimal` and, when false, says
so rather than implying a guarantee. On live data it proves `OPTIMAL` in about
two seconds across ~490 candidates.

The solver uses a fixed random seed so repeated requests give the same squad
(blueprint §29). With several workers under a time limit CP-SAT is not
bit-for-bit deterministic, so that only fully holds where optimality is proven —
which is the normal case.

## The multi-gameweek planner

Choosing a squad for every gameweek at once has an astronomical state space —
15 players from ~600, times bank, times banked free transfers, times horizon.
But the question a manager actually asks is narrower: **when** to spend
transfers, and whether a hit is worth taking.

So the planner branches on that decision. At each gameweek every surviving
state splits into *roll* / *one transfer* / *two with a hit*, the single-gameweek
optimiser decides **which** players to move, and beam search keeps the strongest
paths. Without pruning the tree is 3^horizon paths, each needing a solver run.

States are ranked on points banked **plus** what the squad is still worth over
the remaining horizon. Ranking on points alone would favour hoarding transfers
and leave a weak squad going into the last gameweeks.

Rejected branches are kept and returned, so the UI can show what was considered
and dismissed rather than asserting a single answer.

```bash
curl "http://localhost:8000/api/v1/planner/1?horizon=5&beam_width=4"
```

Typical cost: **~24 optimiser solves in about 1.5 seconds** at the default beam
width of 4. Width 4 is the default because it found a hit-free path worth 186.2
where width 3 took a −8 hit for 185.7 — at effectively the same runtime.

### Free transfer rules

Verified against `game_config.rules`: `max_extra_free_transfers = 4`, so one per
gameweek plus four banked, **capped at five**. Transfers taken as a hit do not
consume banked ones.

### Two things it deliberately guards against

**Planning into gameweeks with no projections.** The horizon truncates to
gameweeks that actually have data and says so in `truncation_note`. Without
this the search plans into empty gameweeks that score zero per node while the
totals still look complete.

**Planning a locked gameweek.** It starts from the first gameweek whose deadline
has not passed — advice about a squad you can no longer change is not advice.

## The accuracy loop

Recommendations are computed on demand, so grading them later needs a record of
what was actually advised. Viewing `/decisions/{manager_id}` snapshots the
captain, lineup and transfer calls — **but only if the deadline has not passed**.
Advice recorded afterwards would be "predicting" a result already visible, which
would flatter the history into meaninglessness.

Once a gameweek finishes, `POST /feedback/{id}/score-all` grades each snapshot
against what actually happened. Three different questions get measured:

| Metric | Question | Why it exists |
|---|---|---|
| `error` | Were the projected points right? | Calibration |
| `regret` | Was it the best available choice? | Decision quality |
| `override_delta` | Did ignoring us help or hurt? | Trust |

**Regret matters more than error.** A captain projected at 6 who scores 11 has a
large error and *zero* regret if nobody in the squad scored more — the decision
was correct even though the number was not. Reporting error alone would grade
that as a failure.

Grading needs actual results in `player_gameweek_stats`:

```bash
curl -X POST "http://localhost:8000/api/v1/projections/backtest/ingest-history?limit=200"
```

### An early honest result

Scored retrospectively against GW1 (with leakage, so illustrative only), the
model looked poor: it named Isak as captain for 2 points when the best available
option scored 11, and its XI would have scored 29 against the 39 actually
achieved. That is the point of the feature — the track record is visible whether
or not it flatters the model.

## Debugging

Set `SQL_ECHO=true` in `backend/.env` to log every SQL query.

### Frontend: beware hydration mismatches

Rendering a locale-formatted date (`toLocaleString`) during SSR produces
different text on the server (UTC) than in the browser (local timezone). React
then bails out of hydration and **silently strips every event handler off the
page** — effects still run, so data loads and the page looks fine, but no click
does anything. Gate locale-dependent output behind a `mounted` flag.

## The Redis cache, and what it deliberately does not cache

Redis had been carrying nothing. The only operations against it were two health
check pings — 22 commands and 0 B stored in a month — so it was a credential to
manage in exchange for nothing.

What it caches now is the per-request manager endpoints. Loading the dashboard
once fans out into four handlers that each resolve the squad from scratch — the
squad view, the state banner, the recommendation and the planner — so FPL was
receiving four identical requests for the same picks within a second or two.
`fetch_manager_picks` and `fetch_manager_info` are wrapped, which means all four
call sites benefit without any of them changing.

### Why the bootstrap is never cached

It is the biggest payload and looks like the obvious win, which is exactly the
trap. The bootstrap is read only by the sync, and the sync's purpose is to spot
what changed: `detect_changes` diffs the incoming snapshot against the stored
one to find injuries, suspensions and price moves. Serve it a cached snapshot
and it concludes that nothing moved. The 30-minute cron would keep running,
keep reporting success, and never surface another piece of news.

That failure is silent, which is what makes it worth a test rather than a
comment. `test_bootstrap_is_never_cached` asserts two consecutive calls both
reach FPL and that Redis is not touched.

### Why the TTL is only 90 seconds

A manager's picks are immutable once a deadline has passed, which argues for a
long TTL. But the same response carries `entry_history` — points, overall rank,
bank, squad value — and those move while matches are being played. Ninety
seconds absorbs one page load's duplicates without live points ever looking
stuck.

### It fails open

Every operation swallows Redis errors and falls through to the loader. A read
failure, a write failure, or Redis being entirely unreachable costs latency and
nothing else. This is load-bearing in the other direction: the app worked
without Redis before, and adding a cache must not quietly turn it into a hard
dependency. Three tests cover those paths, and `CACHE_ENABLED=false` bypasses
Redis completely.

`GET /api/v1/health/cache` reports hit rate. Counters are process-local and
reset on restart.

## Telegram alerts

Everything upstream of this already worked. Change detection ran every fifteen
minutes, filtered events down to the ones affecting a particular squad, and
wrote them to `alerts` — where they sat until someone opened the dashboard,
which required already suspecting something had happened. This is the last mile.

Telegram over email or push because it costs nothing and needs no
infrastructure: no SMTP credentials, no SendGrid account, no service worker, no
VAPID keys. One authenticated POST per message.

### Linking without accounts

There are no user accounts — a manager is an FPL entry id. So a Telegram chat
and a squad have to be introduced:

    dashboard  -> mint a single-use code, return t.me/<bot>?start=<code>
    manager    -> opens it, presses Start
    Telegram   -> POSTs /api/v1/telegram/webhook with that code
    webhook    -> resolves code to entry id, stores the chat id

Codes are single use and expire in fifteen minutes because they travel through
a URL. A live leaked code would let someone point their own Telegram at another
manager's alerts — small blast radius, since an FPL squad is public and the
alerts reveal nothing the FPL website does not, but a code that never expires is
a standing invitation.

The webhook's only authentication is the secret token Telegram echoes in
`X-Telegram-Bot-Api-Secret-Token`. The URL is public; without checking it,
anyone could forge an update and bind their chat to any squad.

### Consent has two degrees

They are different requests and conflating them is annoying:

    Pause        keep the link, stop sending. Resume from the dashboard alone.
    Disconnect   forget the chat id. Requires Telegram again to come back.

### Delivered once, not once per refresh

`Alert.notified_at` is the whole reason this is usable. It is deliberately
distinct from `read_at`, which records a click in the UI — an alert can be
delivered and never read, or read having never been sent. Without it, an
unchanged injury would be re-sent on all ninety-six refreshes a day, and the
channel would be muted by the first afternoon.

It is stamped even when Telegram rejects the message. Retrying a permanently
failing send every fifteen minutes for ever is worse than dropping one
notification that is still sitting in the dashboard.

Two further limits: only `critical` and `warning` are pushed (`info` is real but
not worth a phone buzz), and a single run sends at most six messages before
collapsing the rest into a "…and N more" line, so a mass FPL status change does
not arrive as fifty notifications.

### It fails open

Delivery is wrapped in the same `step()` isolation as every other refresh stage.
A Telegram outage, a revoked token or a manager who blocked the bot must not
fail a refresh whose real work succeeded — the alert is saved and visible
regardless. `TELEGRAM_BOT_TOKEN` being empty disables the whole feature
cleanly, and the UI reports it as unavailable rather than offering a button that
cannot work.

### Setup

    python scripts/telegram_setup.py whoami        # verify the token
    python scripts/telegram_setup.py set-webhook   # register, generating a secret
    python scripts/telegram_setup.py info          # what Telegram thinks

## Scheduling: why QStash rather than GitHub Actions

GitHub Actions was the original scheduler and it does not keep time. Measured
on this repository over four days: **100 runs a day configured, 7.1 actually
delivered**, a median gap of 157 minutes and a worst gap of 9.5 hours. The
scheduler is documented as best-effort, and it drops missed slots rather than
queuing them — so raising the frequency does not help, it only increases the
number of slots dropped. Going from `*/30` to `*/15` changed nothing measurable.

QStash runs a real schedule against the same `POST /api/v1/jobs/refresh`
endpoint, and it was already part of the Upstash account this project uses for
Redis. `scripts/qstash_schedule.py` manages it, so the schedule lives in the
repository rather than being something someone once clicked in a console:

    python scripts/qstash_schedule.py test      # deliver one refresh now
    python scripts/qstash_schedule.py create    # create the recurring schedule
    python scripts/qstash_schedule.py list

At `*/15` that is 96 messages a day against a 500/day free tier.

The GitHub workflow is deliberately left in place. Two schedulers that fail in
different ways, pointed at an idempotent endpoint, are better than one.

### The timeout is the part that matters

A measured delivery took **87 seconds** — a cold Render instance plus a full
rebuild. QStash's default timeout is far below that, and a timeout counts as a
failed delivery, so QStash would retry a refresh that was in fact still running.
Every scheduled run would become two or three overlapping rebuilds. The script
sets `Upstash-Timeout: 5m` for that reason.

Retries are set to 3, which is safe only because the refresh is idempotent: it
upserts the same FPL data rather than appending.

Authentication is the existing `X-Job-Token`, forwarded by QStash via
`Upstash-Forward-X-Job-Token`. QStash also signs its requests; verifying that
signature would be worth adding as defence in depth, but the token already
means an attacker needs a secret rather than just the URL.

## Deployment

Three hosts, all free. Supabase and Upstash already run in the cloud, so the
only pieces that die when your PC shuts down are the API and the scheduler.

| Piece | Host | Notes |
|---|---|---|
| Frontend | Vercel | `NEXT_PUBLIC_API_URL` -> the Render URL |
| API | Render | `render.yaml` blueprint, Docker, Frankfurt |
| Postgres | Supabase | already cloud |
| Redis | Upstash | already cloud |
| Scheduler | GitHub Actions | `.github/workflows/refresh.yml`, every 30 min |

### Do not enable the in-process scheduler in production

`SCHEDULER_ENABLED` runs an asyncio loop inside the API process. A free Render
service is suspended after roughly 15 minutes without inbound traffic, and a
suspended process runs no loop — so the scheduler stops with nothing in the
logs to say so. `render.yaml` pins it to `false` on purpose.

The refresh workflow calls `POST /api/v1/jobs/refresh` from outside instead,
which works whether the service is awake or cold. Two consequences worth
knowing:

- **GitHub disables scheduled workflows after 60 days of repository
  inactivity.** Push a commit or re-enable it manually, or the data quietly
  goes stale.
- GitHub's cron is best-effort and can run late. FPL prices settle around
  01:30 UK, so a delayed run can miss a crossing. Tighten the schedule around
  that window if price alerts matter to you.

A useful side effect: Supabase pauses free projects after about a week idle,
and a 30-minute cron keeps yours awake.

### Order of operations

1. **Rotate credentials** if the Supabase password or Upstash token has ever
   been pasted anywhere. Then `git init`, commit, push.
2. **Render** -> New -> Blueprint -> this repo. It reads `render.yaml` and
   prompts for `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `JOB_TOKEN` and
   `CORS_ORIGINS`. Take the first four from `backend/.env`; leave
   `CORS_ORIGINS` until step 3 gives you the domain.
3. **Vercel** -> import the repo, root directory `frontend`, and set
   `NEXT_PUBLIC_API_URL` to the Render URL. Then put the Vercel domain into
   Render's `CORS_ORIGINS` and redeploy the API.
4. **GitHub** -> Settings -> Secrets -> Actions: add `API_BASE_URL` (the Render
   URL) and `JOB_TOKEN` (byte-identical to Render's, or the refresh gets a
   401). Run the workflow once with *Run workflow* to confirm.
5. **Migrations** run against Supabase from your machine — `migrate.bat`. There
   is no release-phase hook in the blueprint, so a schema change means running
   Alembic yourself before the deploy that needs it.

### What the free tier costs you

The API sleeps when idle, so the first page load after a quiet spell takes
around 50 seconds. Only you feel it — the cron retries through cold starts
(`--retry 2 --retry-delay 30 --retry-connrefused`), so data stays fresh
regardless.

Watch memory on the first solve. Both optimisers request four search workers
(`num_search_workers = 4` in `services/transfers.py` and
`services/dream_team.py`), which was tuned on a desktop; a free instance has
far less CPU and RAM. If `/dream-team` returns 502s, drop that to 1 — it also
makes the result fully deterministic, since worker count is what made two
identical calls disagree.

## Responsive layout

The dashboard is a single scrolling page that has to work from a 320px phone to
a wide desktop. Four rules keep it that way.

**Tap targets are keyed to the pointer, not the width.** `src/lib/ui.ts` holds
the shared control classes. The default is a 36px-tall target; it shrinks to the
compact 28px desktop chrome only under `sm:pointer-fine:` — wide screen *and* a
precise pointer. A touch tablet at 800px therefore keeps the big targets, which
a width-only breakpoint would have taken away.

**Controls are never disabled from zooming.** `layout.tsx` exports `viewport`
for theme colour only. Next writes the viewport meta tag itself, and
`maximumScale`/`userScalable` are deliberately left unset — blocking pinch-zoom
would make the dense tables unusable for anyone who needs to magnify them.

**Tables drop columns by priority rather than scrolling.** Nine columns cannot
fit a phone. Secondary figures carry `hidden sm:table-cell` (or `md:` where the
content is long prose), and what a reader still needs folds under the player's
name instead — position and team in the projections table, the raw FPL news line
in the change feed. The result fits 341px inside a 375px viewport with no
horizontal scrolling anywhere on the page.

**The planner tree is drawn twice and CSS picks one.** A six-column tree is
1320px wide, so the phone gets a 116px-node variant at 846px instead. The
geometry is *not* chosen in JavaScript: doing that requires a `resize` or
`matchMedia` `change` event to fire, and those do not arrive in every
environment — the tree can then be left at the wrong scale with no way to
recover. Both sizes render and a media query hides one. The duplicate costs a
few dozen SVG nodes and cannot get it wrong.

One global rule lives in `globals.css`: inputs and selects hold at 16px below
`sm`, because iOS Safari zooms the whole page when a focused control's text is
smaller than that.

## Build progress

- [x] **Phase 1 — Foundation:** FastAPI, Supabase Postgres, Upstash Redis, Next.js, health check
- [x] **Phase 2 — FPL Data:** adapters, 4 tables, sync jobs, squad import, dashboard UI
- [x] **Phase 3 — Projection v1:** expected minutes, custom FDR, xPts + component breakdown, backtest harness
- [x] **Phase 4 — Decisions:** OR-Tools transfer optimizer, exact XI/bench/captain, computed confidence
- [x] **Phase 5 — News:** deterministic parser (no LLM, no cost), availability events, evidence retained
- [x] **Phase 6 — Alerts:** change detection, per-squad alerts, pre-emptive price warnings, scheduled refresh *(SSE still to do)*
- [x] **Phase 7 — Planner:** beam-search transfer paths, branching decision tree UI
- [x] **Phase 8 — Hardening:** 417 tests, structured logging, rate limits, security headers, CI
- [x] **Phase 9 — Feedback loop:** recommendation snapshots, post-GW scoring, accuracy dashboard
