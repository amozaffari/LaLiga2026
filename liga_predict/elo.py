"""Goal-margin-weighted Elo ratings maintained across La Liga and Segunda División.

Running Elo over both divisions means promoted clubs arrive with a rating earned
from real Segunda División matches instead of an arbitrary prior.
"""

import math

from .config import TOP_DIV

BASE_K = 20.0
HOME_ADV = 60.0  # Elo points added to the home side inside the expectation
INIT_TOP = 1450.0  # debut rating when a club first appears in La Liga
INIT_SECOND = 1350.0  # debut rating when a club first appears in Segunda División
MEAN_RATING = 1500.0
SEASON_REGRESSION = 0.25  # fraction reverted toward the league mean each summer
# Division-change adjustments. A club's Segunda Elo systematically overstates
# its top-flight strength: with no adjustment, promoted clubs shed ~60 Elo on
# average during their first La Liga season (n=75 since 2001) while relegated
# clubs gain ~50 in Segunda. These offsets are applied the moment a club changes
# tier and were tuned so that the first-season rating drift of promoted and
# relegated clubs matches that of clubs that stayed put (all four groups within
# ±6 Elo). They also improve the walk-forward backtest (log loss 0.984 -> 0.979).
PROMOTION_ADJ = -130.0
RELEGATION_ADJ = +120.0


class Elo:
    def __init__(self):
        self.ratings: dict[str, float] = {}
        self.division: dict[str, str] = {}  # division each club was last seen in
        self.last_season: str | None = None  # season code of the last match replayed

    def get(self, team: str, div: str = TOP_DIV) -> float:
        if team not in self.ratings:
            self.ratings[team] = INIT_TOP if div == TOP_DIV else INIT_SECOND
            self.division[team] = div
        elif self.division[team] != div:
            # First sighting in a new tier: promoted (-> top) or relegated (-> second).
            self.ratings[team] += PROMOTION_ADJ if div == TOP_DIV else RELEGATION_ADJ
            self.division[team] = div
        return self.ratings[team]

    @staticmethod
    def expected_home(diff: float) -> float:
        """Win expectancy for the home side given (home - away + HOME_ADV) rating diff."""
        return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

    def update(self, home: str, away: str, hg: int, ag: int, div: str) -> None:
        rh, ra = self.get(home, div), self.get(away, div)
        exp_home = self.expected_home(rh + HOME_ADV - ra)
        score = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        margin_mult = math.log(abs(hg - ag) + 1.0) + 1.0
        delta = BASE_K * margin_mult * (score - exp_home)
        self.ratings[home] = rh + delta
        self.ratings[away] = ra - delta

    def new_season(self) -> None:
        for team in self.ratings:
            self.ratings[team] += SEASON_REGRESSION * (MEAN_RATING - self.ratings[team])
