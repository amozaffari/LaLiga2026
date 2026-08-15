"""Monte Carlo simulation of the upcoming La Liga season.

Ranking follows La Liga's tiebreak order: points, then head-to-head points
among the tied teams, then head-to-head goal difference, then overall goal
difference, then goals scored. (For three-way-plus ties the mini-league is
applied once rather than recursively — a negligible simplification.)
"""

from typing import NamedTuple

import numpy as np
import pandas as pd

from .config import TOP_DIV, UPCOMING_SEASON
from .data_sources.fixtures import load_fixtures
from .goals_model import MAX_GOALS, GoalsModel
from .pipeline import replay_history

N_RELEGATED = 3


class SeasonContext(NamedTuple):
    """Everything expensive, computed once: fixtures, fitted model, Elo ratings."""

    fixtures: pd.DataFrame
    model: GoalsModel
    ratings: dict[str, float]


def build_context() -> SeasonContext:
    top, elo = replay_history()
    # Summer regression toward the mean — but only while the predicted season is
    # absent from the data. Once its matches appear, replay_history has already
    # applied the regression at the season boundary.
    if elo.last_season != UPCOMING_SEASON:
        elo.new_season()

    model = GoalsModel()
    model.fit(top)

    fixtures = load_fixtures()
    clubs = set(fixtures["HomeTeam"]) | set(fixtures["AwayTeam"])
    missing = clubs - set(elo.ratings)
    if missing:
        raise ValueError(f"No Elo rating for: {missing} — check team-name aliases "
                         "in liga_predict/config.py.")
    # Every club in the fixture list plays the top flight this season: this
    # applies the promotion adjustment to clubs last seen in Segunda (a no-op
    # once their first La Liga result of the season is in the data).
    for club in clubs:
        elo.get(club, TOP_DIV)
    return SeasonContext(fixtures, model, dict(elo.ratings))


def match_probabilities(
    ctx: SeasonContext | None = None,
    elo_offsets: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, GoalsModel, dict]:
    """Fixture list with H/D/A probabilities and expected goals for every match.

    elo_offsets are per-team rating adjustments (e.g. market-implied) applied
    on top of the historical Elo before probabilities are computed.
    """
    if ctx is None:
        ctx = build_context()
    off = elo_offsets or {}
    fixtures = ctx.fixtures.copy()
    fixtures["EloHome"] = fixtures["HomeTeam"].map(
        lambda t: ctx.ratings[t] + off.get(t, 0.0))
    fixtures["EloAway"] = fixtures["AwayTeam"].map(
        lambda t: ctx.ratings[t] + off.get(t, 0.0))
    fixtures["EloDiff"] = fixtures["EloHome"] - fixtures["EloAway"]

    lam_h, lam_a = ctx.model.lambdas(fixtures["EloDiff"].to_numpy())
    probs = ctx.model.outcome_probs(fixtures["EloDiff"].to_numpy())
    fixtures["xG_home"] = lam_h
    fixtures["xG_away"] = lam_a
    fixtures[["p_home", "p_draw", "p_away"]] = probs
    return fixtures, ctx.model, ctx.ratings


def _rank_tables(pts, gd, gf, h2h_pts, h2h_gd):
    """Final position of every team in every simulation, La Liga tiebreaks.

    pts/gd/gf: (n_sims, n_teams). h2h_pts/h2h_gd: (n_sims, n_teams, n_teams),
    points / goal difference team i took from its two games against team j.
    """
    # Mini-league among teams level on points: mask (s, i, j) = same points.
    tied = pts[:, :, None] == pts[:, None, :]
    mini_pts = (h2h_pts * tied).sum(axis=2)
    mini_gd = (h2h_gd * tied).sum(axis=2)
    # Lexicographic key; every component fits comfortably inside its slot.
    key = (pts * 1e12 + mini_pts * 1e9 + (mini_gd + 500) * 1e6
           + (gd + 500) * 1e3 + gf)
    order = np.argsort(-key, axis=1, kind="stable")
    position = np.empty_like(order)
    rows_ix = np.arange(pts.shape[0])[:, None]
    position[rows_ix, order] = np.arange(1, pts.shape[1] + 1)
    return position


def simulate_season(
    n_sims: int = 10_000,
    seed: int = 42,
    ctx: SeasonContext | None = None,
    elo_offsets: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (per-match probabilities, season projection table)."""
    fixtures, model, _ = match_probabilities(ctx, elo_offsets)
    teams = sorted(set(fixtures["HomeTeam"]))
    t_idx = {t: i for i, t in enumerate(teams)}
    n_teams = len(teams)
    n_matches = len(fixtures)

    rng = np.random.default_rng(seed)
    n_cells = (MAX_GOALS + 1) ** 2

    # Sample a full scoreline (not just H/D/A) so goal difference breaks ties.
    sampled = np.empty((n_matches, n_sims), dtype=np.int16)
    for i, (lh, la) in enumerate(zip(fixtures["xG_home"], fixtures["xG_away"])):
        flat = model.score_matrix(lh, la).ravel()
        sampled[i] = rng.choice(n_cells, size=n_sims, p=flat / flat.sum())
    hg = sampled // (MAX_GOALS + 1)
    ag = sampled % (MAX_GOALS + 1)

    # Matches already played are fixed to their actual result in every run,
    # so mid-season the simulation only randomises the remaining fixtures.
    for i, r in enumerate(fixtures.itertuples()):
        if r.finished and pd.notna(r.FTHG):
            hg[i, :] = min(int(r.FTHG), MAX_GOALS)
            ag[i, :] = min(int(r.FTAG), MAX_GOALS)

    home_idx = fixtures["HomeTeam"].map(t_idx).to_numpy()
    away_idx = fixtures["AwayTeam"].map(t_idx).to_numpy()

    pts = np.zeros((n_sims, n_teams))
    gd = np.zeros((n_sims, n_teams))
    gf = np.zeros((n_sims, n_teams))
    h2h_pts = np.zeros((n_sims, n_teams, n_teams), dtype=np.int16)
    h2h_gd = np.zeros((n_sims, n_teams, n_teams), dtype=np.int16)
    home_pts = np.where(hg > ag, 3, np.where(hg == ag, 1, 0))
    away_pts = np.where(ag > hg, 3, np.where(hg == ag, 1, 0))
    for i in range(n_matches):
        h, a = home_idx[i], away_idx[i]
        pts[:, h] += home_pts[i]
        pts[:, a] += away_pts[i]
        gd[:, h] += hg[i] - ag[i]
        gd[:, a] += ag[i] - hg[i]
        gf[:, h] += hg[i]
        gf[:, a] += ag[i]
        h2h_pts[:, h, a] += home_pts[i]
        h2h_pts[:, a, h] += away_pts[i]
        h2h_gd[:, h, a] += hg[i] - ag[i]
        h2h_gd[:, a, h] += ag[i] - hg[i]

    position = _rank_tables(pts, gd, gf, h2h_pts, h2h_gd)

    table = pd.DataFrame(
        {
            "team": teams,
            "exp_points": pts.mean(axis=0).round(1),
            "exp_gd": gd.mean(axis=0).round(1),
            "p_champion": (position == 1).mean(axis=0),
            "p_top4": (position <= 4).mean(axis=0),
            "p_top6": (position <= 6).mean(axis=0),
            "p_relegation": (position > n_teams - N_RELEGATED).mean(axis=0),
            "median_position": np.median(position, axis=0).astype(int),
        }
    ).sort_values("exp_points", ascending=False).reset_index(drop=True)

    match_cols = ["gameweek", "kickoff_utc", "HomeTeam", "AwayTeam", "finished",
                  "FTHG", "FTAG", "xG_home", "xG_away", "p_home", "p_draw", "p_away"]
    return fixtures[match_cols], table
