"""
News parser tests.

The regression these guard against is real: reading
`chance_of_playing_this_round` in preference to the news text silently
under-projected 14 doubtful players, because that field is per-round and goes
null or stale between gameweeks.
"""
from datetime import date
import pytest
from app.services.news_parser import (
    parse_news, resolve_availability, DEPARTED_CAUSES,
)


# ── Grammar: every phrasing observed in live FPL data ─────────────────────────

@pytest.mark.parametrize(
    "text,cause,chance",
    [
        ("Hamstring injury - 75% chance of playing", "injury_hamstring", 75),
        ("Knee injury - 50% chance of playing", "injury_knee", 50),
        ("Ankle injury - 25% chance of playing", "injury_ankle", 25),
        ("Knock - 75% chance of playing", "knock", 75),
        ("Unspecified injury - 50% chance of playing", "injury_unspecified", 50),
        ("Lack of match fitness - 75% chance of playing", "fitness", 75),
        ("Thigh injury - Unknown return date", "injury_thigh", None),
        ("Calf injury - Expected back 5 Sep", "injury_calf", None),
        ("Achilles injury - Unknown return date", "injury_achilles", None),
        ("Groin injury - Unknown return date", "injury_groin", None),
        ("Muscular injury - Unknown return date", "injury_muscular", None),
        ("Wrist injury - 75% chance of playing", "injury_wrist", 75),
        ("Arm injury - Unknown return date", "injury_arm", None),
        ("Back injury - Unknown return date", "injury_back", None),
        ("Hip injury - Expected back 5 Sep", "injury_hip", None),
        ("Foot injury - Unknown return date", "injury_foot", None),
        ("Suspended - Expected back 1 Jan", "suspension", None),
        ("Has joined Como permanently", "transfer_out", None),
        ("has returned to Getafe CF", "transfer_out", None),
    ],
)
def test_parses_live_phrasings(text, cause, chance):
    p = parse_news(text)
    assert p.parsed, f"failed to parse: {text!r}"
    assert p.cause == cause
    assert p.chance_percent == chance


def test_lack_of_match_fitness_not_swallowed_by_broader_match():
    # "Lack of match fitness" contains no injury word, but ordering matters:
    # a naive substring pass could mis-assign it.
    assert parse_news("Lack of match fitness - 50% chance of playing").cause == "fitness"


# ── Return dates ─────────────────────────────────────────────────────────────

def test_parses_return_date():
    p = parse_news("Ankle injury - Expected back 14 Sep", today=date(2026, 8, 24))
    assert p.expected_return == date(2026, 9, 14)


def test_parses_single_digit_day():
    p = parse_news("Calf injury - Expected back 5 Sep", today=date(2026, 8, 24))
    assert p.expected_return == date(2026, 9, 5)


def test_infers_next_year_when_month_is_behind():
    # Seen in October, "back 10 Jan" means January of the following year.
    p = parse_news("Knee injury - Expected back 10 Jan", today=date(2026, 10, 1))
    assert p.expected_return == date(2027, 1, 10)


def test_same_year_when_month_is_ahead():
    p = parse_news("Knee injury - Expected back 10 Dec", today=date(2026, 10, 1))
    assert p.expected_return == date(2026, 12, 10)


def test_unknown_return_flagged():
    p = parse_news("Knee injury - Unknown return date")
    assert p.return_unknown is True
    assert p.expected_return is None


def test_invalid_date_does_not_raise():
    # 31 February is not a date; the parser must degrade, not explode.
    p = parse_news("Knee injury - Expected back 31 Feb")
    assert p.expected_return is None


# ── Degenerate input ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["", None, "   "])
def test_empty_input_is_safe(text):
    p = parse_news(text)
    assert p.parsed is False
    assert p.cause is None
    assert p.chance_percent is None


def test_unrecognised_text_marked_unparsed_not_crashed():
    p = parse_news("Some entirely new phrasing FPL has never used")
    assert p.parsed is False
    assert p.cause is None


def test_out_of_range_percentage_rejected():
    p = parse_news("Injury - 500% chance of playing")
    assert p.chance_percent is None


# ── Availability resolution: the precedence that fixed the bug ────────────────

def test_news_text_beats_null_chance_field():
    """The 12-player case: field null, text has a percentage."""
    mult, source, _ = resolve_availability("d", None, "Hamstring injury - 75% chance of playing")
    assert mult == 0.75
    assert source == "news_text"


def test_news_text_beats_stale_zero_chance_field():
    """The Pedro Porro case: field says 0%, text says 75%."""
    mult, source, _ = resolve_availability("d", 0, "Lack of match fitness - 75% chance of playing")
    assert mult == 0.75
    assert source == "news_text"


def test_news_text_beats_contradicting_chance_field():
    """The Kudus case: field 25%, text 50%."""
    mult, source, _ = resolve_availability("d", 25, "Thigh injury - 50% chance of playing")
    assert mult == 0.50
    assert source == "news_text"


def test_chance_field_used_when_news_has_no_percentage():
    mult, source, _ = resolve_availability("d", 60, "Knock - Unknown return date")
    assert mult == 0.60
    assert source == "chance_field"


def test_status_fallback_when_nothing_else_available():
    mult, source, _ = resolve_availability("d", None, "")
    assert mult == 0.55
    assert source.startswith("status:")


@pytest.mark.parametrize("status", ["i", "s", "u", "n"])
def test_hard_status_overrides_stale_optimistic_news(status):
    """
    FPL sometimes leaves a "75% chance" string on a player it has since ruled
    out. Status must win, or we recommend an unavailable player.
    """
    mult, source, _ = resolve_availability(
        status, 75, "Hamstring injury - 75% chance of playing"
    )
    assert mult == 0.0
    assert source.startswith("status:")


def test_departed_player_is_zeroed_regardless_of_status():
    mult, source, parsed = resolve_availability("a", None, "Has joined Como permanently")
    assert mult == 0.0
    assert source == "departed"
    assert parsed.cause in DEPARTED_CAUSES


def test_available_player_with_no_news_is_full():
    mult, _, _ = resolve_availability("a", None, "")
    assert mult == 1.0


def test_multiplier_always_within_bounds():
    for status in ("a", "d", "i", "s", "u", "n"):
        for chance in (None, 0, 50, 100):
            for news in ("", "Knock - 75% chance of playing", "Has joined X permanently"):
                mult, _, _ = resolve_availability(status, chance, news)
                assert 0.0 <= mult <= 1.0
