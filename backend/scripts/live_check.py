"""
Check the live calculation against FPL's own numbers for real managers.

Once a gameweek's matches are all over and FPL has applied its automatic
substitutions, the points worked out here must equal FPL's. Run it after a
gameweek (or during one, to see the projections):

    python scripts/live_check.py 1 2 3 4 5

Reads only public FPL endpoints; needs no database or credentials.
"""
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.live import fixture_state, players_live, team_live  # noqa: E402

BASE = "https://fantasy.premierleague.com/api"


def get(path: str):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


async def main(entries: list[int]) -> int:
    boot = get("/bootstrap-static/")
    gw = next(e["id"] for e in boot["events"] if e["is_current"])
    team_of = {p["id"]: p["team"] for p in boot["elements"]}
    live, fixtures = get(f"/event/{gw}/live/"), get(f"/fixtures/?event={gw}")
    players = players_live(live, fixtures, team_of)
    over = all(fixture_state(f) == "done" for f in fixtures)
    print(f"GW{gw}: {sum(fixture_state(f) == 'done' for f in fixtures)}/{len(fixtures)} matches over")

    mismatches = 0
    for entry in entries:
        picks = get(f"/entry/{entry}/event/{gw}/picks/")
        team = team_live(picks, players)
        h = picks["entry_history"]
        fpl = h["points"] - h["event_transfers_cost"]
        ours_confirmed = team.points - team.provisional_bonus
        note = "" if ours_confirmed == fpl else "  <-- differs"
        if over and ours_confirmed != fpl and not team.auto_subs:
            mismatches += 1
        print(f"  {entry}: ours {team.points} (incl. {team.provisional_bonus} provisional bonus), "
              f"FPL {fpl}, chip {team.chip}, projected subs {team.auto_subs}{note}")
    return mismatches


if __name__ == "__main__":
    ids = [int(a) for a in sys.argv[1:]] or [1, 2, 3, 4, 5]
    sys.exit(1 if asyncio.run(main(ids)) else 0)
