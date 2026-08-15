"""Prediction-market probabilities from Polymarket's public (keyless) Gamma API.

Two things are read: the La Liga champion market, and per-match markets whose
slugs follow ``lal-{home}-{away}-{YYYY-MM-DD}`` with short team codes.
"""

import json

import pandas as pd
import requests

from ..config import USER_AGENT, canonical_team

GAMMA = "https://gamma-api.polymarket.com"
CHAMPION_EVENT_SLUG = "laliga-2027-champion-20260701200737375"

# Codes used in Polymarket La Liga match-event slugs (canonical name -> code).
MATCH_CODES = {
    "Alavés": "ala", "Athletic Club": "bil", "Atlético Madrid": "mad",
    "Barcelona": "bar", "Celta Vigo": "cel", "Deportivo": "dep", "Elche": "elc",
    "Espanyol": "esp", "Getafe": "get", "Levante": "lev", "Málaga": "mala",
    "Osasuna": "osa", "Racing Santander": "rrc", "Rayo Vallecano": "ray",
    "Real Betis": "bet", "Real Madrid": "rea", "Real Sociedad": "rso",
    "Sevilla": "sev", "Valencia": "val", "Villarreal": "vil",
}


def _get(path: str, **params):
    resp = requests.get(f"{GAMMA}{path}", params=params,
                        headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _yes_price(market: dict) -> float:
    return float(json.loads(market["outcomePrices"])[0])


def title_probs() -> pd.DataFrame:
    """De-vigged champion probabilities per team from the season winner market."""
    event = _get("/events", slug=CHAMPION_EVENT_SLUG)[0]
    rows = []
    for m in event["markets"]:
        label = m.get("groupItemTitle", "")
        team = canonical_team(label)
        # Skip "Team A/B/C" / "Other" placeholder markets: they never map to a club.
        if team in MATCH_CODES:
            rows.append({"team": team, "p_title_market": _yes_price(m)})
    df = pd.DataFrame(rows)
    df["p_title_market"] /= df["p_title_market"].sum()
    return df


def match_probs(home: str, away: str, kickoff_utc) -> dict | None:
    """De-vigged H/D/A probabilities for one fixture, or None if no market exists."""
    date = pd.Timestamp(kickoff_utc).strftime("%Y-%m-%d")
    slug = f"lal-{MATCH_CODES[home]}-{MATCH_CODES[away]}-{date}"
    events = _get("/events", slug=slug)
    if not events:
        return None

    # Questions read "Will <Home long name> win on <date>?", "... end in a draw?",
    # "Will <Away long name> win on <date>?". The event title is "<Home> vs. <Away>"
    # in the same long names, so match on those rather than on our short names.
    title = events[0].get("title", "")
    long_home, _, long_away = title.partition(" vs. ")
    p_home = p_draw = p_away = None
    for m in events[0]["markets"]:
        q = m["question"].lower()
        if "draw" in q:
            p_draw = _yes_price(m)
        elif long_home and long_home.lower() in q:
            p_home = _yes_price(m)
        elif long_away and long_away.lower() in q:
            p_away = _yes_price(m)
    if None in (p_home, p_draw, p_away):
        return None
    total = p_home + p_draw + p_away
    return {"pm_home": p_home / total, "pm_draw": p_draw / total,
            "pm_away": p_away / total, "slug": slug}
