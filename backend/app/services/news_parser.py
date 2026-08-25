"""
Parse FPL's own news strings into structured availability data.

No LLM is involved and none is needed: FPL's `player.news` field is strictly
formulaic, so a deterministic parser handles it exactly and for free. That
matters because the alternative — an LLM re-deriving what FPL already tells us
— would be slower, cost money, and be less reliable.

Observed grammar (verified against all 118 live news strings, 2026-08-24):

    "{cause} - {availability}"

    cause         "Hamstring injury" | "Knock" | "Lack of match fitness"
                  | "Unspecified injury" | "Suspended" | ...
    availability  "75% chance of playing"
                  | "Unknown return date"
                  | "Expected back 14 Sep"

An LLM becomes worth adding only for genuinely unstructured sources (club
press conferences, journalist posts) that arrive *before* FPL updates. The
provider hook for that is `app/services/news_llm.py`, which is optional.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

# "75% chance of playing"
RE_CHANCE = re.compile(r"(\d{1,3})\s*%\s*chance of playing", re.I)
# "Expected back 14 Sep" / "Expected back 5 September"
RE_RETURN = re.compile(
    r"expected back\s+(\d{1,2})\s+([A-Za-z]{3,9})(?:\s+(\d{4}))?", re.I
)
RE_UNKNOWN_RETURN = re.compile(r"unknown return date", re.I)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Cause phrase -> canonical category. Checked longest-first so
# "lack of match fitness" is not swallowed by a broader match.
CAUSE_PATTERNS: list[tuple[str, str]] = [
    ("lack of match fitness", "fitness"),
    ("unspecified injury", "injury_unspecified"),
    ("hamstring", "injury_hamstring"),
    ("achilles", "injury_achilles"),
    ("muscular", "injury_muscular"),
    ("knee", "injury_knee"),
    ("ankle", "injury_ankle"),
    ("thigh", "injury_thigh"),
    ("groin", "injury_groin"),
    ("calf", "injury_calf"),
    ("foot", "injury_foot"),
    ("hip", "injury_hip"),
    ("back", "injury_back"),
    ("arm", "injury_arm"),
    ("wrist", "injury_wrist"),
    ("shoulder", "injury_shoulder"),
    ("head", "injury_head"),
    ("illness", "illness"),
    ("virus", "illness"),
    ("knock", "knock"),
    ("suspended", "suspension"),
    ("suspension", "suspension"),
    ("red card", "suspension"),
    ("loan", "loan"),
    ("transferred", "transfer_out"),
    # Departed players. FPL writes these without the " - " separator:
    #   "Has joined Como permanently" / "has returned to Getafe CF"
    ("has joined", "transfer_out"),
    ("has returned to", "transfer_out"),
    ("international duty", "international_duty"),
    ("personal reasons", "personal"),
    ("self-isolating", "unavailable_other"),
]

# Cause categories that mean the player has left the league entirely — they
# should never be recommended, regardless of any stale percentage.
DEPARTED_CAUSES = {"transfer_out", "loan"}

# Status codes FPL uses in `player.status`
STATUS_LABEL = {
    "a": "available",
    "d": "doubtful",
    "i": "injured",
    "s": "suspended",
    "u": "unavailable",
    "n": "not_in_squad",
}

# Fallback minutes multiplier per status, used only when no percentage is
# available anywhere.
STATUS_MULTIPLIER = {
    "a": 1.00,
    "d": 0.55,
    "i": 0.00,
    "s": 0.00,
    "u": 0.00,
    "n": 0.00,
}


@dataclass
class ParsedNews:
    raw: str
    cause: str | None                 # canonical category
    cause_text: str | None            # the phrase as FPL wrote it
    chance_percent: int | None        # from the news string
    expected_return: date | None
    return_unknown: bool
    parsed: bool                      # did anything match?

    def as_dict(self) -> dict:
        return {
            "raw": self.raw,
            "cause": self.cause,
            "cause_text": self.cause_text,
            "chance_percent": self.chance_percent,
            "expected_return": self.expected_return.isoformat() if self.expected_return else None,
            "return_unknown": self.return_unknown,
            "parsed": self.parsed,
        }


def _parse_return_date(text: str, today: date | None = None) -> date | None:
    """
    Read "Expected back 14 Sep".

    FPL omits the year, so it is inferred: a month more than three behind the
    current one belongs to next year (a "back 10 Jan" note seen in October).
    """
    m = RE_RETURN.search(text)
    if not m:
        return None

    day_s, month_s, year_s = m.groups()
    month = MONTHS.get(month_s[:3].lower())
    if month is None:
        return None

    today = today or datetime.now(timezone.utc).date()
    year = int(year_s) if year_s else today.year
    if not year_s and month < today.month - 3:
        year += 1

    try:
        return date(year, month, int(day_s))
    except ValueError:
        return None


def parse_news(news: str | None, today: date | None = None) -> ParsedNews:
    """Parse one FPL news string. Safe on empty/unrecognised input."""
    raw = (news or "").strip()
    if not raw:
        return ParsedNews(raw="", cause=None, cause_text=None, chance_percent=None,
                          expected_return=None, return_unknown=False, parsed=False)

    # Match the cause against the segment BEFORE the " - " separator only.
    #
    # Matching the whole string is wrong: the availability clause contains the
    # word "back" ("Expected back 14 Sep"), so "Suspended - Expected back 1 Jan"
    # would be tagged injury_back — as would any cause listed after "back" in
    # CAUSE_PATTERNS (knock, suspension, loan) whenever a return date is given.
    head = raw.split(" - ")[0].strip() if " - " in raw else raw
    head_lowered = head.lower()

    cause = None
    cause_text = None
    for needle, category in CAUSE_PATTERNS:
        if needle in head_lowered:
            cause = category
            cause_text = head
            break

    chance = None
    m = RE_CHANCE.search(raw)
    if m:
        value = int(m.group(1))
        if 0 <= value <= 100:
            chance = value

    return ParsedNews(
        raw=raw,
        cause=cause,
        cause_text=cause_text,
        chance_percent=chance,
        expected_return=_parse_return_date(raw, today),
        return_unknown=bool(RE_UNKNOWN_RETURN.search(raw)),
        parsed=bool(cause or chance is not None
                    or RE_UNKNOWN_RETURN.search(raw) or RE_RETURN.search(raw)),
    )


def resolve_availability(
    status: str,
    chance_field: int | None,
    news: str | None,
    today: date | None = None,
) -> tuple[float, str, ParsedNews]:
    """
    Best available minutes multiplier for a player, plus why.

    Precedence, and the reason for it:

    1. A hard status (injured / suspended / unavailable) wins outright. FPL
       sometimes leaves a stale "75% chance" string on a player it has since
       marked injured.
    2. Otherwise the percentage in the news string beats
       `chance_of_playing_this_round`. That field is per-round and goes stale
       or null between gameweeks, while the news text is kept current — 11 of
       22 doubtful players had a usable percentage in the text and nothing in
       the field.
    3. Then the field itself, then the status fallback.

    Returns (multiplier 0-1, source label, parsed news).
    """
    parsed = parse_news(news, today=today)

    if status in ("i", "s", "u", "n"):
        return STATUS_MULTIPLIER.get(status, 0.0), f"status:{STATUS_LABEL.get(status, status)}", parsed

    # A player who has left the league cannot play, whatever else the text says
    if parsed.cause in DEPARTED_CAUSES:
        return 0.0, "departed", parsed

    if parsed.chance_percent is not None:
        return parsed.chance_percent / 100.0, "news_text", parsed

    if chance_field is not None:
        return max(0.0, min(1.0, chance_field / 100.0)), "chance_field", parsed

    return STATUS_MULTIPLIER.get(status, 1.0), f"status:{STATUS_LABEL.get(status, status)}", parsed
