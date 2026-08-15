"""Current La Liga rosters from Biwenger's public competition feed (keyless).

Biwenger is the largest Spanish fantasy game; its competition endpoint returns
every player in the league with club, position, market price, fantasy points
this season and last (AS.com scoring), the points of the last few rounds, and
a status flag (ok / doubt / injured / sanctioned / unknown / discarded). It is
the La Liga stand-in for the FPL bootstrap used in the Premier League version.

The raw payload is cached in data/raw and refreshed on every run; the cache is
the fallback when the site is unreachable.
"""

import json

import pandas as pd
import requests

from ..config import BIWENGER_URL, RAW_DIR, UPCOMING_SEASON, USER_AGENT, canonical_team

CACHE = RAW_DIR / f"biwenger_{UPCOMING_SEASON}.json"
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD", 5: "COACH"}
# Chance of playing the next match by status flag.
AVAILABILITY = {"ok": 1.0, "doubt": 0.5, "unknown": 0.5, "injured": 0.0,
                "sanctioned": 0.0, "discarded": 0.0}


def _payload() -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(BIWENGER_URL, params={"lang": "en", "score": 1},
                            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                            timeout=30)
        resp.raise_for_status()
        data = resp.json()["data"]
        CACHE.write_text(json.dumps(data))
        return data
    except (requests.RequestException, ValueError, KeyError):
        if CACHE.exists():
            print(f"(using cached {CACHE.name}; Biwenger fetch failed)")
            return json.loads(CACHE.read_text())
        raise


def _form_points(fitness) -> tuple[float, int]:
    """(points, games) over the recent rounds; non-numeric entries = did not play."""
    pts, games = 0.0, 0
    for v in fitness or []:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            pts += float(v)
            games += 1
    return pts, games


def current_players() -> pd.DataFrame:
    """One row per La Liga player (coaches and free agents dropped).

    Columns: id, name, team_name, position, price, status, avail,
    pts_prev (last season), pts_now (this season), games_now,
    form_pts / form_games (recent rounds).
    """
    data = _payload()
    teams = {int(k): canonical_team(v["name"]) for k, v in data["teams"].items()}
    rows = []
    for p in data["players"].values():
        team = teams.get(p.get("teamID"))
        if team is None or p.get("position") == 5:
            continue
        form_pts, form_games = _form_points(p.get("fitness"))
        rows.append({
            "id": p["id"],
            "name": p["name"],
            "team_name": team,
            "position": POSITIONS.get(p.get("position"), "?"),
            "price": float(p.get("price") or 0.0),
            "status": p.get("status") or "unknown",
            "avail": AVAILABILITY.get(p.get("status"), 0.5),
            "pts_prev": float(p.get("pointsLastSeason") or 0.0),
            "pts_now": float(p.get("points") or 0.0),
            "games_now": int((p.get("playedHome") or 0) + (p.get("playedAway") or 0)),
            "form_pts": form_pts,
            "form_games": form_games,
            "news": p.get("statusInfo") or "",
        })
    df = pd.DataFrame(rows)
    return df


def season_rounds_played() -> int:
    """How many rounds of the current season Biwenger marks as finished."""
    data = _payload()
    rounds = (data.get("season") or {}).get("rounds") or []
    return sum(1 for r in rounds if r.get("status") == "finished")
