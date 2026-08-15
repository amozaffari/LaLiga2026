"""Player-level squad strength model (Biwenger rosters).

Bottom-up team strength from the full current roster:

- Each player's value is last season's La Liga fantasy points (AS.com scoring,
  via Biwenger). Players without La Liga points last season (foreign signings,
  promoted-club squads, academy debuts) are valued from their market price via
  a per-position regression on log(price), fit on players who have both.
- In-season, a player's rate blends last season with current form (points per
  game over the recent rounds, scaled to a season).
- Team strength = the top-15 player values (season horizon ignores short
  injuries; match horizon discounts by availability: doubt 50%, injured /
  suspended 0%).
- The points -> Elo scale is CALIBRATED, not invented: end-of-last-season Elo
  is regressed on squad points across the clubs that played La Liga last
  season. (No multi-season fantasy archive exists for La Liga, unlike FPL's
  vaastav dataset, so the fit uses one season's cross-section — 17 clubs.)
"""

import numpy as np
import pandas as pd

from .config import TOP_DIV
from .data_sources.biwenger import current_players
from .data_sources.football_data import load_matches
from .elo import Elo

TOP_N = 15
OFFSET_CAP = 75.0
# Weight of the squad-implied rating when shrinking Elo toward it. Elo already
# encodes team strength, so the squad signal adjusts rather than adds.
BLEND_W = 0.4
FORM_W = 0.3  # in-season weight on recent form vs last season's level
ROUNDS_PER_SEASON = 38


def _squad_points(players: pd.DataFrame, value_col: str) -> pd.Series:
    """Top-N player values summed per team."""
    return (players.sort_values(value_col, ascending=False)
            .groupby("team_name")[value_col]
            .apply(lambda s: s.head(TOP_N).sum()))


def _last_completed_season() -> tuple[str, dict[str, float], set[str]]:
    """(season code, end-of-season Elo per team, clubs in the top flight that season)."""
    matches = load_matches()
    seasons = sorted(matches["Season"].unique())
    # The last season with a full top-flight programme (>= 300 of 380 games).
    complete = [s for s in seasons
                if (matches[(matches["Season"] == s) & (matches["Div"] == TOP_DIV)]
                    .shape[0] >= 300)]
    target = complete[-1]
    elo = Elo()
    current = None
    end_elos: dict[str, float] = {}
    for row in matches.itertuples(index=False):
        if row.Season != current:
            if current == target:
                break
            if current is not None:
                elo.new_season()
            current = row.Season
        elo.update(row.HomeTeam, row.AwayTeam, row.FTHG, row.FTAG, row.Div)
    end_elos = dict(elo.ratings)
    top = matches[(matches["Season"] == target) & (matches["Div"] == TOP_DIV)]
    clubs = set(top["HomeTeam"]) | set(top["AwayTeam"])
    return target, end_elos, clubs


def calibrate_pts_to_elo(verbose: bool = False,
                         roster: pd.DataFrame | None = None) -> tuple[float, float]:
    """(slope, intercept) mapping top-15 squad points to Elo.

    Fit on the clubs that were in La Liga last season: their current squad's
    last-season points against their end-of-last-season Elo. Squads are the
    current ones (rosters move over the summer), so the fit is a little noisy;
    the slope is what matters and it is well determined."""
    roster = current_players() if roster is None else roster
    season, end_elos, clubs = _last_completed_season()
    squad = _squad_points(roster, "pts_prev")
    rows = [{"squad_pts": pts, "elo": end_elos[team]}
            for team, pts in squad.items() if team in clubs and team in end_elos]
    df = pd.DataFrame(rows)
    slope, intercept = np.polyfit(df["squad_pts"], df["elo"], 1)
    if verbose:
        pred = slope * df["squad_pts"] + intercept
        r2 = 1 - ((df["elo"] - pred) ** 2).sum() / ((df["elo"] - df["elo"].mean()) ** 2).sum()
        print(f"calibration (season {season}): {len(df)} clubs, "
              f"{slope:.3f} Elo per squad point, R^2 = {r2:.2f}")
    return float(slope), float(intercept)


def current_roster() -> pd.DataFrame:
    """Every current player with a value in expected fantasy points.

    value_season ignores current fitness (season horizon); value_match
    discounts by availability. In-season, form blends into the rate.
    """
    df = current_players()

    # Value newcomers from market price: fit pts_prev ~ log(price) per position.
    df["value_base"] = df["pts_prev"]
    known = df["pts_prev"] > 0
    df["log_price"] = np.log(df["price"].clip(lower=1e5))
    for pos, group in df.groupby("position"):
        g = group[known.reindex(group.index, fill_value=False)]
        if len(g) < 10:
            continue
        slope, intercept = np.polyfit(g["log_price"], g["pts_prev"], 1)
        estimate = (slope * group["log_price"] + intercept).clip(lower=0)
        fill = group["value_base"] <= 0
        df.loc[group.index[fill], "value_base"] = estimate[fill]

    # In-season: blend last season's level with current form (points per game
    # over the recent rounds, scaled to a season). Before the first round every
    # player has no form, so the blend is a no-op.
    has_form = df["form_games"] > 0
    if has_form.any() and df["games_now"].sum() > 0:
        rate = (df["form_pts"] / df["form_games"].replace(0, np.nan)) * ROUNDS_PER_SEASON
        df.loc[has_form, "value_base"] = ((1 - FORM_W) * df.loc[has_form, "value_base"]
                                          + FORM_W * rate[has_form].clip(lower=0))

    df["value_season"] = df["value_base"].where(df["status"] != "discarded", 0.0)
    df["value_match"] = df["value_base"] * df["avail"]
    return df[["id", "name", "team_name", "position", "price", "status", "news",
               "pts_prev", "pts_now", "games_now", "form_pts", "form_games",
               "avail", "value_season", "value_match"]]


def squad_strength(horizon: str, ratings: dict[str, float]) -> pd.DataFrame:
    """Per-team squad strength and the Elo adjustment it implies.

    The offset shrinks the team's current Elo toward its squad-implied rating
    (weight BLEND_W) rather than adding on top — Elo already measures strength,
    so the roster signal corrects it instead of double-counting it.
    """
    roster = current_roster()
    col = "value_season" if horizon == "season" else "value_match"
    strength = _squad_points(roster, col).rename("squad_pts").to_frame()
    slope, intercept = calibrate_pts_to_elo(roster=roster)
    strength["implied_elo"] = slope * strength["squad_pts"] + intercept
    strength["current_elo"] = pd.Series(ratings).reindex(strength.index)
    strength["elo_offset"] = (BLEND_W
                              * (strength["implied_elo"] - strength["current_elo"])
                              ).clip(-OFFSET_CAP, OFFSET_CAP)
    return strength.sort_values("squad_pts", ascending=False)


def squad_elo_offsets(horizon: str, ratings: dict[str, float]) -> dict[str, float]:
    return squad_strength(horizon, ratings)["elo_offset"].to_dict()
