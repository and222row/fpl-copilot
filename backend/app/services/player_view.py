from app.models.fpl import Player

POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
STATUS_NAMES = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
    "n": "Not in squad",
}

PHOTO_BASE = "https://resources.premierleague.com/premierleague/photos/players"


def player_photo(code: int) -> str | None:
    """FPL headshot URL, or None when the code is missing."""
    return f"{PHOTO_BASE}/110x140/p{code}.png" if code else None


def player_summary(p: Player, team_short: str) -> dict:
    return {
        "id": p.id,
        "name": p.web_name,
        "photo": player_photo(p.code),
        "full_name": f"{p.first_name} {p.second_name}".strip(),
        "team": team_short,
        "position": POSITION_NAMES.get(p.position, "UNK"),
        "price": round(p.now_cost / 10, 1),
        "total_points": p.total_points,
        "form": p.form,
        "ep_this": p.ep_this,
        "ep_next": p.ep_next,
        "selected_by_percent": p.selected_by_percent,
        "status": p.status,
        "status_label": STATUS_NAMES.get(p.status, p.status),
        "news": p.news,
        "chance_this": p.chance_of_playing_this_round,
        "minutes": p.minutes,
    }
