"""Fixtures, kickoff times and results for the season being predicted.

Two keyless sources are combined and cached in data/raw:

- ESPN's public scoreboard: one request returns every match of the season with
  the UTC kickoff, live status, score and venue. It does not carry the official
  matchday (round) number.
- fixturedownload.com's La Liga feed: the same 380 fixtures with the official
  round number (its kickoff *times* are unreliable, so ESPN's are preferred).

Either source may be down on a given day; the last good copy of each is cached
so the pipeline degrades to slightly stale data instead of failing.
"""

import json

import pandas as pd
import requests

from ..config import (ESPN_SCOREBOARD_URLS, ESPN_SEASON_DATES, FIXTUREDOWNLOAD_URL,
                      RAW_DIR, UPCOMING_SEASON, USER_AGENT, canonical_team)

ESPN_CACHE = RAW_DIR / f"espn_{UPCOMING_SEASON}_SP1.json"
FD_CACHE = RAW_DIR / f"fixturedownload_{UPCOMING_SEASON}_SP1.json"


def _get_json(url: str, cache, params: dict | None = None):
    """Fetch JSON, refresh the cache on success, fall back to the cache on failure."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for _attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=30,
                                headers={"User-Agent": USER_AGENT,
                                         "Accept": "application/json"})
            if resp.status_code == 200:
                data = resp.json()
                cache.write_text(json.dumps(data))
                return data
        except (requests.RequestException, ValueError):
            pass
    if cache.exists():
        print(f"(using cached {cache.name}; live fetch from {url.split('/')[2]} failed)")
        return json.loads(cache.read_text())
    return None


def _utc(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_convert("UTC") if t.tzinfo else t.tz_localize("UTC")


def _espn_events() -> pd.DataFrame | None:
    data = None
    for url in ESPN_SCOREBOARD_URLS:
        data = _get_json(url, ESPN_CACHE, {"dates": ESPN_SEASON_DATES, "limit": 500})
        if data and data.get("events"):
            break
    if not data or not data.get("events"):
        return None
    rows = []
    for ev in data["events"]:
        comp = ev["competitions"][0]
        sides = {}
        for c in comp["competitors"]:
            sides[c["homeAway"]] = (canonical_team(c["team"]["displayName"]),
                                    pd.to_numeric(c.get("score"), errors="coerce"))
        state = ev["status"]["type"]["state"]  # pre / in / post
        finished = bool(ev["status"]["type"].get("completed")) or state == "post"
        rows.append({
            "kickoff_utc": _utc(ev["date"]),
            "HomeTeam": sides["home"][0], "AwayTeam": sides["away"][0],
            "finished": finished,
            "FTHG": sides["home"][1] if finished else float("nan"),
            "FTAG": sides["away"][1] if finished else float("nan"),
            "venue": (comp.get("venue") or {}).get("fullName"),
        })
    return pd.DataFrame(rows)


def _fixturedownload() -> pd.DataFrame | None:
    data = _get_json(FIXTUREDOWNLOAD_URL, FD_CACHE)
    if not data:
        return None
    rows = [{
        "gameweek": int(f["RoundNumber"]),
        "fd_date": _utc(f["DateUtc"]),
        "HomeTeam": canonical_team(f["HomeTeam"]),
        "AwayTeam": canonical_team(f["AwayTeam"]),
        "fd_FTHG": pd.to_numeric(f.get("HomeTeamScore"), errors="coerce"),
        "fd_FTAG": pd.to_numeric(f.get("AwayTeamScore"), errors="coerce"),
    } for f in data]
    return pd.DataFrame(rows)


def load_fixtures() -> pd.DataFrame:
    """All 380 fixtures with canonical team names, matchday, UTC kickoff, status/result.

    Columns: gameweek, kickoff_utc, HomeTeam, AwayTeam, finished, FTHG, FTAG, venue.
    """
    espn = _espn_events()
    fd = _fixturedownload()
    if espn is None and fd is None:
        raise RuntimeError("Could not load fixtures from ESPN or fixturedownload "
                           "(no network and no cache in data/raw).")

    if fd is None:
        # ESPN only: no official round numbers. Approximate the matchday from
        # each fixture's rank in the chronological order (10 games per round).
        print("(fixturedownload unavailable: matchdays approximated from kickoff order)")
        df = espn.sort_values("kickoff_utc").reset_index(drop=True)
        df["gameweek"] = df.index // 10 + 1
    elif espn is None:
        print("(ESPN unavailable: kickoff times taken from fixturedownload, which "
              "only guarantees the date)")
        df = fd.rename(columns={"fd_date": "kickoff_utc", "fd_FTHG": "FTHG",
                                "fd_FTAG": "FTAG"})
        df["finished"] = df["FTHG"].notna()
        df["venue"] = None
    else:
        df = espn.merge(fd, on=["HomeTeam", "AwayTeam"], how="left")
        unmatched = df["gameweek"].isna()
        if unmatched.any():
            print(f"(warning: {int(unmatched.sum())} fixtures missing a matchday number: "
                  f"{df.loc[unmatched, ['HomeTeam', 'AwayTeam']].values.tolist()})")
            df.loc[unmatched, "gameweek"] = 0
        # ESPN scores win; fixturedownload fills in if ESPN hasn't posted yet.
        fd_done = df["fd_FTHG"].notna() & ~df["finished"]
        df.loc[fd_done, ["FTHG", "FTAG"]] = df.loc[fd_done, ["fd_FTHG", "fd_FTAG"]].to_numpy()
        df.loc[fd_done, "finished"] = True
        df = df.drop(columns=["fd_date", "fd_FTHG", "fd_FTAG"])

    df["gameweek"] = df["gameweek"].astype(int)
    df["kickoff_utc"] = pd.to_datetime(df["kickoff_utc"], utc=True)
    df["finished"] = df["finished"].astype(bool)
    cols = ["gameweek", "kickoff_utc", "HomeTeam", "AwayTeam", "finished",
            "FTHG", "FTAG", "venue"]
    return df[cols].sort_values(["kickoff_utc", "HomeTeam"]).reset_index(drop=True)
