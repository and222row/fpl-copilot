"""
Contract tests against the live FPL API.

Blueprint §21 and §26: the FPL endpoints are unofficial and can change without
notice. These assert the *shape* we depend on, so a vendor change surfaces here
rather than as silently wrong projections in production.

Network-marked — skip with:  pytest -m "not network"
"""
import pytest
from app.services.fpl_client import (
    fetch_bootstrap, fetch_fixtures, fetch_manager_picks, fetch_manager_info,
    fetch_player_detail, close_client,
)

pytestmark = [pytest.mark.network, pytest.mark.slow]

# The bootstrap payload is ~1MB, so fetch it once and reuse the parsed data.
# The HTTP client itself cannot be reused: `fpl_client` caches one at module
# level, pytest-asyncio gives each test its own event loop, and an httpx client
# bound to a closed loop raises "Event loop is closed". So the payload is
# cached but the client is closed after every test.
_BOOTSTRAP_CACHE: dict = {}


@pytest.fixture(autouse=True)
async def _reset_http_client():
    """Ensure each test starts and ends with no client bound to its loop."""
    await close_client()
    yield
    await close_client()


@pytest.fixture
async def bootstrap():
    if not _BOOTSTRAP_CACHE:
        _BOOTSTRAP_CACHE.update(await fetch_bootstrap())
    return _BOOTSTRAP_CACHE


# ── bootstrap-static ─────────────────────────────────────────────────────────

async def test_bootstrap_has_the_sections_we_read(bootstrap):
    for key in ("teams", "elements", "events", "element_types",
                "game_config", "chips"):
        assert key in bootstrap, f"bootstrap lost '{key}'"


async def test_premier_league_has_twenty_teams(bootstrap):
    assert len(bootstrap["teams"]) == 20


async def test_season_has_thirty_eight_gameweeks(bootstrap):
    assert len(bootstrap["events"]) == 38


async def test_team_strength_fields_present(bootstrap):
    """The custom FDR prior is built from these."""
    t = bootstrap["teams"][0]
    for field in ("id", "name", "short_name", "strength_attack_home",
                  "strength_attack_away", "strength_defence_home",
                  "strength_defence_away"):
        assert field in t, f"team lost '{field}'"


async def test_player_fields_the_projection_model_depends_on(bootstrap):
    p = bootstrap["elements"][0]
    required = (
        # identity
        "id", "team", "element_type", "web_name", "first_name", "second_name",
        # price and selection
        "now_cost", "selected_by_percent", "total_points", "form",
        # availability
        "status", "news", "chance_of_playing_this_round",
        # minutes
        "minutes", "starts", "starts_per_90",
        # per-90 rates driving xPts
        "expected_goals_per_90", "expected_assists_per_90",
        "expected_goals_conceded_per_90", "saves_per_90",
        "defensive_contribution", "defensive_contribution_per_90",
        # scoring inputs
        "bonus", "bps", "yellow_cards", "red_cards", "goals_scored", "assists",
        "clean_sheets", "goals_conceded", "own_goals",
        # set-piece roles
        "penalties_order", "corners_and_indirect_freekicks_order",
        "direct_freekicks_order",
        # price change
        "price_change_percent", "price_change_projections",
        "transfers_in_event", "transfers_out_event",
    )
    missing = [f for f in required if f not in p]
    assert not missing, f"player fields removed by FPL: {missing}"


async def test_scoring_rules_are_published(bootstrap):
    """
    We sync point values rather than hardcoding them. If FPL stops publishing
    them, the fallback silently takes over — so fail loudly here instead.
    """
    scoring = bootstrap["game_config"]["scoring"]
    for key in ("long_play", "short_play", "goals_scored", "assists",
                "clean_sheets", "goals_conceded", "saves", "bonus",
                "yellow_cards", "red_cards", "own_goals",
                "defensive_contribution"):
        assert key in scoring, f"scoring lost '{key}'"


async def test_positional_scoring_uses_expected_keys(bootstrap):
    scoring = bootstrap["game_config"]["scoring"]
    for key in ("goals_scored", "clean_sheets", "goals_conceded",
                "defensive_contribution"):
        assert set(scoring[key]) == {"GKP", "DEF", "MID", "FWD"}, (
            f"{key} position keys changed: {scoring[key]}"
        )


async def test_squad_rules_match_our_optimiser_constants(bootstrap):
    """If FPL changes squad size or the club cap, the optimiser is wrong."""
    from app.services.transfers import SQUAD_COMPOSITION, MAX_PER_CLUB

    rules = bootstrap["game_config"]["rules"]
    assert rules["squad_squadsize"] == sum(SQUAD_COMPOSITION.values()) == 15
    assert rules["squad_squadplay"] == 11
    assert rules["squad_team_limit"] == MAX_PER_CLUB

    for et in bootstrap["element_types"]:
        assert SQUAD_COMPOSITION[et["id"]] == et["squad_select"], (
            f"{et['singular_name_short']} squad_select changed to {et['squad_select']}"
        )


async def test_formation_limits_match_our_enumeration(bootstrap):
    """The eight legal formations are derived from these min/max values."""
    from app.services.lineup import FORMATIONS

    limits = {
        et["id"]: (et["squad_min_play"], et["squad_max_play"])
        for et in bootstrap["element_types"]
    }
    derived = {
        (d, m, f)
        for d in range(limits[2][0], limits[2][1] + 1)
        for m in range(limits[3][0], limits[3][1] + 1)
        for f in range(limits[4][0], limits[4][1] + 1)
        if d + m + f == 10
    }
    assert set(FORMATIONS) == derived, (
        f"FPL formation limits changed; expected {derived}"
    )


async def test_static_content_url_encodes_the_season(bootstrap):
    """Season detection for `scoring_rules` parses this URL."""
    url = bootstrap["game_config"]["settings"]["static_content_url"]
    assert any(
        len(part) == 7 and part[:4].isdigit() and part[4] == "_"
        for part in url.rstrip("/").split("/")
    ), f"cannot derive season from {url!r}"


# ── fixtures ─────────────────────────────────────────────────────────────────

async def test_fixtures_expose_all_three_completion_flags():
    """
    `finished_provisional` is the flag that means "played". Reading `finished`
    alone made a fully-played gameweek look like it never happened.
    """
    fixtures = await fetch_fixtures()
    assert len(fixtures) == 380
    f = fixtures[0]
    for field in ("id", "event", "team_h", "team_a", "team_h_score",
                  "team_a_score", "finished", "finished_provisional",
                  "started", "minutes", "kickoff_time",
                  "team_h_difficulty", "team_a_difficulty"):
        assert field in f, f"fixture lost '{field}'"


# ── manager endpoints ────────────────────────────────────────────────────────

async def test_manager_info_shape():
    info = await fetch_manager_info(1)
    for field in ("id", "name", "player_first_name", "player_last_name",
                  "summary_overall_points", "summary_overall_rank",
                  "last_deadline_bank", "last_deadline_value"):
        assert field in info, f"manager info lost '{field}'"


async def test_manager_picks_shape():
    picks = await fetch_manager_picks(1, 1)
    assert "picks" in picks and len(picks["picks"]) == 15

    pick = picks["picks"][0]
    for field in ("element", "position", "is_captain", "is_vice_captain",
                  "multiplier"):
        assert field in pick, f"pick lost '{field}'"

    # Slots 1-11 are the XI, 12-15 the bench
    slots = sorted(p["position"] for p in picks["picks"])
    assert slots == list(range(1, 16))

    assert sum(1 for p in picks["picks"] if p["is_captain"]) == 1
    assert sum(1 for p in picks["picks"] if p["is_vice_captain"]) == 1

    history = picks.get("entry_history", {})
    for field in ("bank", "value", "event_transfers", "points"):
        assert field in history, f"entry_history lost '{field}'"


async def test_player_detail_history_shape():
    """Backtest ground truth comes from here."""
    detail = await fetch_player_detail(1)
    assert "history" in detail
    if detail["history"]:
        h = detail["history"][0]
        for field in ("round", "fixture", "total_points", "minutes",
                      "goals_scored", "assists", "clean_sheets", "bonus",
                      "value", "was_home", "opponent_team"):
            assert field in h, f"history lost '{field}'"


# ── Parser contract ──────────────────────────────────────────────────────────

async def test_live_news_strings_still_parse(bootstrap):
    """
    The availability parser is regex-based. If FPL introduces a new phrasing,
    this fails here rather than silently degrading every projection.
    """
    from app.services.news_parser import parse_news

    with_news = [e for e in bootstrap["elements"] if (e.get("news") or "").strip()]
    unparsed = [e["news"] for e in with_news if not parse_news(e["news"]).parsed]

    assert not unparsed, (
        f"{len(unparsed)}/{len(with_news)} news strings unrecognised — "
        f"add patterns to news_parser.CAUSE_PATTERNS: {unparsed[:5]}"
    )
