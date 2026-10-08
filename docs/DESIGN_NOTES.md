# Design notes

Why the model, the optimisers and the data pipeline work the way they do,
including the bugs that shaped them. Written as each feature was built, so
some passages describe how a problem was found; where later work changed the
picture (accounts, store billing, monitoring), the current behaviour is in
[ARCHITECTURE.md](ARCHITECTURE.md) and the other documents in this folder.

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
than a solver. See [lineup.py](../backend/app/services/lineup.py).

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
[confidence.py](../backend/app/services/confidence.py).

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

[news_parser.py](../backend/app/services/news_parser.py) handles all of it with
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

Shared helpers in [fpl_sync.py](../backend/app/services/fpl_sync.py):
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

**External trigger** — QStash on a real schedule, with
[`.github/workflows/refresh.yml`](../.github/workflows/refresh.yml) as a backup
(see [Scheduling](#scheduling-why-qstash-rather-than-github-actions)).
Necessary on a free tier that sleeps after inactivity, because an in-process
loop dies with the process.

The interval has a hard floor of 5 minutes: a refresh takes over a minute, and
hammering the unofficial FPL endpoints risks getting the app blocked.

### Securing it

A refresh rewrites thousands of rows and makes hundreds of upstream calls, so it
must not be publicly triggerable. Callers must send `X-Job-Token` matching
`JOB_TOKEN`, compared with `secrets.compare_digest`. Unset leaves it open
locally; in production an unset token refuses every call.

### Who gets alerts

A team is registered in `tracked_managers` when an account proves it owns the
team, and refreshed whenever its squad is loaded. (Before accounts existed, any
team ID whose squad was loaded was registered.) The job generates alerts for
each tracked team, and one unreachable team ID does not stop the others.

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

## Chip timing

FPL issues each chip with an expiry — two sets, one per half of the season, and
an unused chip is simply lost. That makes this a **bounded optimal-stopping**
problem rather than a scoring one. "Is this a good week to Triple Captain?" is
the wrong question: a twelve-point captain is a poor use in GW5 and an obvious
one in GW18, and the number is identical. What matters is whether the current
opportunity is good enough given how many chances remain.

So every recommendation carries three quantities: what the chip is worth now,
the best it reaches inside the projection horizon, and how many gameweeks are
left before it expires.

### Layered by how much each part can be trusted

    fixture shape    counting. Doubles and blanks are facts.
    availability     FPL's own record of what you have played.
    valuation        the projection model, with all its uncertainty.
    the verdict      a heuristic on top of that, so the weakest link.

That ordering is surfaced in the response and the UI, because chip advice
*compounds* model error: a transfer risks one projection, a wildcard stakes
fifteen at once, and a triple captain triples the error on one. The model has a
single accuracy reading and it was poor.

### The double-gameweek watcher is the part worth having

`alert_on_shape_changes` counts fixtures per team per gameweek and raises an
alert the first time a double or blank appears. It is the only piece here that
involves no model at all, and the only one you could not work out by eye —
doubles are created months after the fixture list is published, when postponed
matches are rearranged, and nobody re-reads a schedule from July. It is
deduplicated on the alert title, because the refresh runs ninety-six times a
day.

### Three bugs this shipped with, and what they were

**Wildcard valued at a one-week horizon.** A wildcard is permanent, so solving
for a single gameweek picks a squad nobody would keep and overstates the chip
roughly fourfold — 15.9 pts/GW against a true 4.1. It now solves across the
horizon; a free hit legitimately keeps horizon=1, which is the whole difference
between the two chips.

**Comparing unlike quantities.** `build_dream_team` reports
`xi_pts + captain.gw_xpts`, but `LineupResult.starting_xpts` excludes the
captain's extra copy. Comparing them subtracted a captain from one side only and
inflated every gap by roughly a premium's score.

**A baseline built from one observation.** The mean of a single value is that
value, so every ratio came out exactly 1.0 and the reasoning was circular:
"15.9 is close to a typical 15.9". With one data point there is no typical week,
so the advisor now says so instead.

    GET /api/v1/chips/{manager_id}       full advice
    GET /api/v1/chips/fixtures/shape     doubles and blanks, squad-independent

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

### Reconnection

Managed providers drop idle connections — Upstash's free tier does so within
minutes, which showed up as a degraded health check on an otherwise healthy
service. The client pings idle pooled connections before reuse, retries with
backoff, and rebuilds the pool once if a command still fails.

## Telegram alerts

Everything upstream of this already worked. Change detection ran every fifteen
minutes, filtered events down to the ones affecting a particular squad, and
wrote them to `alerts` — where they sat until someone opened the dashboard,
which required already suspecting something had happened. This is the last mile.

Telegram over email or push because it costs nothing and needs no
infrastructure: no SMTP credentials, no SendGrid account, no service worker, no
VAPID keys. One authenticated POST per message.

### Linking a chat to a squad

Built before accounts existed, when a manager was just an FPL entry id. The
endpoints now require the caller to own the team, but the linking itself is
unchanged — a Telegram chat and a squad still have to be introduced:

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

## Bandwidth: the refresh was rewriting the database to say nothing happened

Render suspended the service on 24 Sep for exhausting the 5 GB free bandwidth
allowance in twenty-five days. Measured afterwards, FPL traffic accounted for
only 0.43 GB of that — the bootstrap is 0.16 MB gzipped and fixtures 0.02 MB.
The rest was the refresh talking to Supabase.

Two causes, both of them work that achieved nothing:

**Every row was updated on every sync.** `row.updated_at = utcnow()` ran
unconditionally inside each upsert loop, so the timestamp always differed and
SQLAlchemy emitted an UPDATE for all 612 players, 20 teams and 38 gameweeks —
about 670 writes per refresh to record that nothing had changed. At 96 refreshes
a day that is 1.6 million statements in under a month. `_touch_if_changed` now
stamps the timestamp only when `is_modified` reports the row genuinely dirty.
Measured on two consecutive syncs with nothing moving in between: **653 writes,
then 1**.

**Projections were rebuilt regardless.** Team strength and 3,060 projection rows
were recomputed every run, producing identical numbers, because FPL prices move
once a day and news a handful of times. The refresh now reads the answer
`detect_changes` has already produced and skips both when nothing moved.

The skip only applies when the preceding steps succeeded. A failed bootstrap
also reports zero events — because nothing was written, not because nothing
moved — and an existing test caught the first version of the gate treating those
as the same thing.

### A suspended service does not deploy

Render resumed the build it had before suspension rather than pulling the
newest commit. The fix had been pushed *while* the service was suspended, so
the auto-deploy webhook had nothing to deploy to, and on resume the old image
simply restarted. Confirmed after the 1 Oct reset: the refresh response carried
`gameweek_shape` and `notifications` but no skip marker, which places the
running build at the commit before the fix.

Worth checking explicitly after any suspension — the service being healthy says
nothing about which commit it is healthy on.

### What actually caused it

Making the scheduler reliable. While GitHub Actions was dropping ninety-three
percent of scheduled runs, the waste stayed under the allowance by accident.
Moving to QStash, which honours the schedule, turned 7 effective refreshes a day
into 96 and exposed work that had always been pointless. The frequency was the
trigger; the write amplification was the bug.

Frequency is now every 30 minutes rather than 15 — halving it also keeps the
retry traffic well inside QStash's 500 messages a day, which 96 scheduled runs
with three retries each could have breached on its own.

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

## Debugging

Set `SQL_ECHO=true` in `backend/.env` to log every SQL query.

### Frontend: beware hydration mismatches

Rendering a locale-formatted date (`toLocaleString`) during SSR produces
different text on the server (UTC) than in the browser (local timezone). React
then bails out of hydration and **silently strips every event handler off the
page** — effects still run, so data loads and the page looks fine, but no click
does anything. Gate locale-dependent output behind a `mounted` flag.

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

## Build history

The blueprint's original phases, before the mobile app work. The mobile
phases (accounts, onboarding, trial, billing, push, deletion, security review,
observability) are described across the other documents in `docs/`.

- [x] **Phase 1 — Foundation:** FastAPI, Supabase Postgres, Upstash Redis, Next.js, health check
- [x] **Phase 2 — FPL Data:** adapters, 4 tables, sync jobs, squad import, dashboard UI
- [x] **Phase 3 — Projection v1:** expected minutes, custom FDR, xPts + component breakdown, backtest harness
- [x] **Phase 4 — Decisions:** OR-Tools transfer optimizer, exact XI/bench/captain, computed confidence
- [x] **Phase 5 — News:** deterministic parser (no LLM, no cost), availability events, evidence retained
- [x] **Phase 6 — Alerts:** change detection, per-squad alerts, pre-emptive price warnings, scheduled refresh *(SSE still to do)*
- [x] **Phase 7 — Planner:** beam-search transfer paths, branching decision tree UI
- [x] **Phase 8 — Hardening:** 417 tests, structured logging, rate limits, security headers, CI
- [x] **Phase 9 — Feedback loop:** recommendation snapshots, post-GW scoring, accuracy dashboard
