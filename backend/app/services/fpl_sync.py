from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.fpl import Team, Player, Gameweek, Fixture, utcnow
from app.models.projections import ScoringRules, ChipWindow
from app.services.fpl_client import fetch_bootstrap, fetch_fixtures


def _f(val) -> float:
    """FPL returns numbers as strings, nulls as None. Coerce to float."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _i(val) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _dt(val: str | None) -> datetime | None:
    """FPL timestamps look like '2026-08-15T17:30:00Z'."""
    if not val:
        return None
    return datetime.fromisoformat(val.replace("Z", "+00:00"))


async def sync_bootstrap(db: AsyncSession) -> dict:
    """
    Fetch FPL bootstrap-static and upsert teams, gameweeks and players.
    Order matters: teams before players (FK), gameweeks before fixtures.
    """
    data = await fetch_bootstrap()

    # ── Teams ────────────────────────────────────────────────────────────────
    for t in data.get("teams", []):
        row = await db.get(Team, t["id"])
        if row is None:
            row = Team(id=t["id"])
            db.add(row)
        row.name = t["name"]
        row.short_name = t["short_name"]
        row.strength = _i(t.get("strength"))
        row.strength_overall_home = _i(t.get("strength_overall_home"))
        row.strength_overall_away = _i(t.get("strength_overall_away"))
        row.strength_attack_home = _i(t.get("strength_attack_home"))
        row.strength_attack_away = _i(t.get("strength_attack_away"))
        row.strength_defence_home = _i(t.get("strength_defence_home"))
        row.strength_defence_away = _i(t.get("strength_defence_away"))
        row.updated_at = utcnow()
    teams_count = len(data.get("teams", []))
    await db.flush()

    # ── Gameweeks ────────────────────────────────────────────────────────────
    for gw in data.get("events", []):
        row = await db.get(Gameweek, gw["id"])
        if row is None:
            row = Gameweek(id=gw["id"])
            db.add(row)
        row.name = gw["name"]
        row.deadline_time = _dt(gw["deadline_time"])
        row.finished = bool(gw.get("finished"))
        row.is_current = bool(gw.get("is_current"))
        row.is_next = bool(gw.get("is_next"))
        row.is_previous = bool(gw.get("is_previous"))
        row.average_entry_score = _i(gw.get("average_entry_score"))
        row.highest_score = _i(gw.get("highest_score"))
        row.updated_at = utcnow()
    gws_count = len(data.get("events", []))
    await db.flush()

    # ── Players ──────────────────────────────────────────────────────────────
    for p in data.get("elements", []):
        row = await db.get(Player, p["id"])
        if row is None:
            row = Player(id=p["id"])
            db.add(row)
        row.team_id = p["team"]
        row.first_name = p["first_name"]
        row.second_name = p["second_name"]
        row.web_name = p["web_name"]
        row.code = _i(p.get("code"))
        row.position = p["element_type"]
        row.now_cost = _i(p.get("now_cost"))
        row.total_points = _i(p.get("total_points"))
        row.form = _f(p.get("form"))
        row.selected_by_percent = _f(p.get("selected_by_percent"))
        row.status = p.get("status") or "a"
        row.chance_of_playing_this_round = p.get("chance_of_playing_this_round")
        row.chance_of_playing_next_round = p.get("chance_of_playing_next_round")
        row.news = p.get("news") or ""
        row.ep_this = _f(p.get("ep_this"))
        row.ep_next = _f(p.get("ep_next"))
        row.minutes = _i(p.get("minutes"))
        row.starts = _i(p.get("starts"))
        row.goals_scored = _i(p.get("goals_scored"))
        row.assists = _i(p.get("assists"))
        row.clean_sheets = _i(p.get("clean_sheets"))
        row.goals_conceded = _i(p.get("goals_conceded"))
        row.yellow_cards = _i(p.get("yellow_cards"))
        row.red_cards = _i(p.get("red_cards"))
        row.saves = _i(p.get("saves"))
        row.bonus = _i(p.get("bonus"))
        row.bps = _i(p.get("bps"))
        row.influence = _f(p.get("influence"))
        row.creativity = _f(p.get("creativity"))
        row.threat = _f(p.get("threat"))
        row.ict_index = _f(p.get("ict_index"))
        row.own_goals = _i(p.get("own_goals"))
        row.penalties_saved = _i(p.get("penalties_saved"))
        row.penalties_missed = _i(p.get("penalties_missed"))
        row.expected_goals = _f(p.get("expected_goals"))
        row.expected_assists = _f(p.get("expected_assists"))
        row.expected_goal_involvements = _f(p.get("expected_goal_involvements"))
        row.expected_goals_conceded = _f(p.get("expected_goals_conceded"))
        row.transfers_in_event = _i(p.get("transfers_in_event"))
        row.transfers_out_event = _i(p.get("transfers_out_event"))

        # Defensive contribution (raw stat counts, not points)
        row.clearances_blocks_interceptions = _i(p.get("clearances_blocks_interceptions"))
        row.recoveries = _i(p.get("recoveries"))
        row.tackles = _i(p.get("tackles"))
        row.defensive_contribution = _i(p.get("defensive_contribution"))

        # Per-90 rates — the projection model's primary inputs
        row.starts_per_90 = _f(p.get("starts_per_90"))
        row.expected_goals_per_90 = _f(p.get("expected_goals_per_90"))
        row.expected_assists_per_90 = _f(p.get("expected_assists_per_90"))
        row.expected_goals_conceded_per_90 = _f(p.get("expected_goals_conceded_per_90"))
        row.goals_conceded_per_90 = _f(p.get("goals_conceded_per_90"))
        row.clean_sheets_per_90 = _f(p.get("clean_sheets_per_90"))
        row.saves_per_90 = _f(p.get("saves_per_90"))
        row.defensive_contribution_per_90 = _f(p.get("defensive_contribution_per_90"))
        row.points_per_game = _f(p.get("points_per_game"))

        # Set-piece roles (v1.1 signal)
        row.penalties_order = p.get("penalties_order")
        row.corners_freekicks_order = p.get("corners_and_indirect_freekicks_order")
        row.direct_freekicks_order = p.get("direct_freekicks_order")

        # Price change — FPL publishes its own projections
        row.price_change_percent = _f(p.get("price_change_percent"))
        row.price_change_hourly_rate = _i(p.get("price_change_hourly_rate"))
        row.price_change_projections = p.get("price_change_projections")
        row.price_change_locked_until = _dt(p.get("price_change_locked_until"))
        row.cost_change_event = _i(p.get("cost_change_event"))
        row.cost_change_start = _i(p.get("cost_change_start"))

        row.updated_at = utcnow()
    players_count = len(data.get("elements", []))

    # ── Scoring rules ────────────────────────────────────────────────────────
    rules_synced = await _sync_scoring_rules(db, data)
    chips_synced = await _sync_chip_windows(db, data)

    await db.commit()

    return {
        "teams": teams_count,
        "gameweeks": gws_count,
        "players": players_count,
        "scoring_rules": rules_synced,
        "chip_windows": chips_synced,
    }


async def _sync_chip_windows(db: AsyncSession, bootstrap: dict) -> int:
    """
    Persist when each chip may be played.

    FPL issues two sets — one per half of the season — and an unused chip is
    lost when its window closes. That expiry is what makes chip advice a timing
    problem rather than a scoring one, so the deadline has to be data we hold
    rather than a number someone remembered.
    """
    chips = bootstrap.get("chips") or []
    if not chips:
        return 0

    existing = {
        (c.name, c.start_event): c
        for c in (await db.execute(select(ChipWindow))).scalars().all()
    }

    for chip in chips:
        name = chip.get("name")
        start = chip.get("start_event")
        stop = chip.get("stop_event")
        if not name or start is None or stop is None:
            continue
        row = existing.get((name, start))
        if row is None:
            db.add(ChipWindow(
                name=name,
                chip_type=chip.get("chip_type") or "",
                start_event=start,
                stop_event=stop,
            ))
        else:
            row.stop_event = stop
            row.chip_type = chip.get("chip_type") or row.chip_type

    await db.commit()
    return len(chips)


async def _sync_scoring_rules(db: AsyncSession, bootstrap: dict) -> str:
    """
    Persist FPL's own scoring table so point values are data, not constants.

    Derives the season key from the static content URL, which looks like
    ".../plfpl-production/2026_27/".
    """
    game_config = bootstrap.get("game_config", {}) or {}
    scoring = game_config.get("scoring")
    if not scoring:
        return "unavailable"

    static_url = (game_config.get("settings", {}) or {}).get("static_content_url", "")
    season = "unknown"
    for part in static_url.rstrip("/").split("/"):
        if len(part) == 7 and part[:4].isdigit() and part[4] == "_":
            season = part
            break

    existing = (await db.execute(
        select(ScoringRules).where(ScoringRules.season == season)
    )).scalars().first()

    if existing is None:
        # Any previously active season is no longer active
        await db.execute(update(ScoringRules).values(is_active=False))
        db.add(ScoringRules(season=season, rules=scoring, is_active=True))
        return f"created {season}"

    existing.rules = scoring
    existing.is_active = True
    existing.synced_at = utcnow()
    return f"updated {season}"


async def sync_fixtures(db: AsyncSession) -> int:
    """Fetch all fixtures and upsert. Requires teams + gameweeks to exist."""
    fixtures = await fetch_fixtures()

    for f in fixtures:
        row = await db.get(Fixture, f["id"])
        if row is None:
            row = Fixture(id=f["id"])
            db.add(row)
        row.gameweek_id = f.get("event")
        row.team_h = f["team_h"]
        row.team_a = f["team_a"]
        row.team_h_score = f.get("team_h_score")
        row.team_a_score = f.get("team_a_score")
        row.team_h_difficulty = _i(f.get("team_h_difficulty") or 3)
        row.team_a_difficulty = _i(f.get("team_a_difficulty") or 3)
        row.finished = bool(f.get("finished"))
        row.finished_provisional = bool(f.get("finished_provisional"))
        row.started = bool(f.get("started"))
        row.minutes = _i(f.get("minutes"))
        row.kickoff_time = _dt(f.get("kickoff_time"))

    await db.commit()
    return len(fixtures)


async def get_current_gameweek(db: AsyncSession) -> Gameweek | None:
    """The GW currently in progress. None during pre-season."""
    result = await db.execute(select(Gameweek).where(Gameweek.is_current.is_(True)))
    return result.scalars().first()


async def get_next_gameweek(db: AsyncSession) -> Gameweek | None:
    """The next GW with an open deadline."""
    result = await db.execute(select(Gameweek).where(Gameweek.is_next.is_(True)))
    return result.scalars().first()


async def get_active_gameweek(db: AsyncSession) -> Gameweek | None:
    """
    Best GW to show a user: current if one is live, otherwise next.
    Falls back to the earliest unfinished GW (covers pre-season).
    """
    gw = await get_current_gameweek(db)
    if gw:
        return gw
    gw = await get_next_gameweek(db)
    if gw:
        return gw
    result = await db.execute(
        select(Gameweek).where(Gameweek.finished.is_(False)).order_by(Gameweek.id)
    )
    return result.scalars().first()

async def get_next_open_gameweek(db: AsyncSession) -> Gameweek | None:
    """
    The earliest gameweek whose deadline has NOT passed.

    This is the gameweek every recommendation should target. `get_active_gameweek`
    returns the gameweek currently being *played*, whose deadline has already
    gone — advising on it produces a transfer the manager cannot make, because
    the squad is locked the moment the deadline passes.

    Falls back to the active gameweek only when every deadline is behind us
    (end of season).
    """
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(Gameweek).order_by(Gameweek.id)
    )).scalars().all()

    for gw in rows:
        deadline = gw.deadline_time
        if deadline is None:
            continue
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline > now:
            return gw

    return await get_active_gameweek(db)


async def get_latest_started_gameweek(db: AsyncSession) -> Gameweek | None:
    """
    The most recent gameweek whose deadline has passed.

    Squad picks only exist for gameweeks that have started, so this is where a
    manager's current squad must be read from — which is not the same gameweek
    the advice targets.
    """
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(Gameweek).order_by(Gameweek.id.desc())
    )).scalars().all()

    for gw in rows:
        deadline = gw.deadline_time
        if deadline is None:
            continue
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline <= now:
            return gw

    return None


def deadline_has_passed(gw: Gameweek) -> bool:
    if gw.deadline_time is None:
        return False
    deadline = gw.deadline_time
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= deadline
