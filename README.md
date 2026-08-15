# LaLiga2026 — La Liga match prediction

**Live site:** <https://amozaffari.github.io/LaLiga2026/> — rebuilt daily at 05:17
UTC by [GitHub Actions](.github/workflows/update.yml): fresh results and odds
are fetched, Elo is updated, the season is re-simulated (played matches locked
to their actual results), the model is re-calibrated against Polymarket, and
the dashboard + site are redeployed. One-time setup: repo Settings → Pages →
Source → **GitHub Actions**.

Predicts La Liga match outcomes and simulates the 2026-27 season, built
entirely on free, keyless data sources. It is the Spanish sibling of
[PL2026](https://github.com/amozaffari/PL2026): same Elo → Poisson → Monte
Carlo pipeline, with every England-specific data source replaced.

## Data sources (all free, no API key)

| Source | What it provides | Used for |
| --- | --- | --- |
| [football-data.co.uk](https://www.football-data.co.uk/spainm.php) | CSVs of every La Liga (SP1) + Segunda División (SP2) match since 2000, incl. closing odds from ~10 bookmakers | Training data, odds baseline |
| [ESPN scoreboard API](https://site.web.api.espn.com/apis/site/v2/sports/soccer/esp.1/scoreboard?dates=20260801-20270630&limit=500) | All 380 fixtures of 2026-27 with UTC kickoff, venue, live status and scores | Season simulation, upcoming predictions, results |
| [fixturedownload.com](https://fixturedownload.com/results/la-liga-2026) | The same fixtures with the official matchday (jornada) number | Matchday grouping (ESPN doesn't carry it) |
| [Biwenger](https://biwenger.as.com/) competition feed | Every La Liga player: club, position, market price, fantasy points this season and last, recent form, injury/suspension status | `squad`, `transfers` commands and the player-level squad model |
| [Open-Meteo](https://open-meteo.com/) | Hourly weather forecast at any coordinates | Kickoff weather at the home stadium (context only) |
| [Polymarket Gamma API](https://gamma-api.polymarket.com/) | Real-money prediction-market prices: LaLiga 2027 champion + per-match H/D/A markets | `markets` command: market probabilities, model-vs-market comparison, blend |

Optional upgrade that needs a (free-tier) API key: [The Odds API](https://the-odds-api.com/)
(`soccer_spain_la_liga`, live pre-match odds — lets the blend model run on
future matches). Every source's raw payload is cached in `data/raw/`, so a
site being down for a day degrades to slightly stale data instead of breaking
the pipeline. All the club-name spellings (football-data "Ath Bilbao", ESPN
"Athletic Club", Polymarket "Athletic Bilbao", Biwenger "Athletic", …) resolve
through one alias table in `liga_predict/config.py`.

## How it works

1. **Elo ratings** are maintained across both La Liga and Segunda División
   (goal-margin weighted, home advantage, 25% regression to the mean each
   summer). Running Elo across both divisions means promoted clubs arrive with
   a rating earned from real matches. Because a Segunda rating systematically
   overstates top-flight strength (promoted clubs shed ~60 Elo on average in
   their first season, n=75 since 2001), a **division-change adjustment**
   (−130 on promotion, +120 on relegation) is applied the moment a club changes
   tier; it was tuned so promoted/relegated clubs drift no more than clubs
   that stayed put, and it improves the backtest.
2. **Expected goals**: two Poisson GLMs (home and away goals) map the pre-match
   Elo difference to scoring rates, fit with exponential time-decay weights.
3. **Match probabilities**: independent-Poisson score matrix with the
   Dixon-Coles low-score correction (rho fit by grid search).
4. **Odds baseline / blend**: bookmaker closing odds are de-vigged into fair
   probabilities; the backtest compares model vs. odds vs. a 50/50 blend.
5. **Season simulation**: 10,000 Monte Carlo runs of all 380 fixtures, sampling
   full scorelines. Tables are ranked with **La Liga's tiebreak order**:
   points, head-to-head points among level teams, head-to-head goal
   difference, then overall goal difference and goals scored.

## Usage

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m liga_predict fetch              # download 26 seasons of SP1+SP2 data
.venv/bin/python -m liga_predict backtest           # walk-forward eval, last 3 seasons
.venv/bin/python -m liga_predict simulate           # 2026-27 Monte Carlo -> output/*.csv
.venv/bin/python -m liga_predict predict            # next matchday probs + weather
.venv/bin/python -m liga_predict predict --matchday 5
.venv/bin/python -m liga_predict markets            # model vs Polymarket (title + matchday)
.venv/bin/python -m liga_predict squad --team "Real Madrid"   # player-level squad strength
.venv/bin/python -m liga_predict transfers          # players new to La Liga, per club
.venv/bin/python -m liga_predict simulate --market-implied   # Elo calibrated to Polymarket
ODDS_API_KEY=... .venv/bin/python -m liga_predict predict    # adds live bookmaker odds + blend
.venv/bin/python -m liga_predict simulate --squad-adjust     # squad-model Elo offsets
.venv/bin/python -m liga_predict history                     # snapshot + match-prediction log
python scripts/plot_predictions.py && python scripts/plot_history.py && python scripts/build_site.py
```

**Player-level squad model** (`liga_predict/squad_model.py`, `squad` command).
Team strength is built bottom-up from the full current roster (Biwenger): each
player is valued at last season's La Liga fantasy points; players with no La
Liga history (foreign signings, promoted-club squads) are valued from their
market price via a per-position regression on log(price); in-season, values
blend 30% current form. Team strength is the top-15 sum, and the points→Elo
conversion is calibrated by regressing end-of-last-season Elo on squad points
across the 17 clubs that played La Liga last season (R² ≈ 0.4 — a single
season's cross-section, since no multi-season fantasy archive like FPL's
vaastav dataset exists for Spain). The resulting rating *shrinks* each club's
Elo 40% toward its squad-implied level (capped ±75). `predict` applies the
match horizon (availability discounts: doubt 50%, injured/suspended 0%) by
default (`--raw` disables); `simulate --squad-adjust` applies the season
horizon as a market-free alternative to `--market-implied` (never stack the
two). Known limits: promoted squads are price-only estimates, and fantasy
points are an attack-tilted quality proxy.

**Prediction history.** `history` writes a weekly snapshot of the projected
table to `history/projections/` and maintains `history/match_predictions.csv`,
where each fixture's probabilities update until kickoff and then freeze — the
model is judged on what it said before the game. The daily CI run commits
`history/` back to the repo and the site shows the probability evolution, last
matchday's predictions vs. results, and a running scoreboard (accuracy, log
loss, Brier).

`--market-implied` iteratively nudges team Elo ratings until simulated title
odds match the Polymarket champion market, then re-simulates all 380 fixtures —
propagating the market's squad-level knowledge (transfers, injuries, managers)
to every match and to the relegation picture. Only teams with >=1% title
probability on either side get calibrated, and market prices below 1% are
read as "about 1%": in a two-horse league a club priced at 0.4% for the title
is not being called a mid-table side, only a non-contender.

Outputs land in `output/`: `season_projection.csv` (title/top-4/relegation
probabilities, expected points), `match_probabilities.csv` (H/D/A probabilities
and xG for all 380 fixtures), `backtest.csv`, `title_market.csv`.

## Backtest results (2023-24 → 2025-26, walk-forward)

| Model | Log loss | Brier | Accuracy |
| --- | --- | --- | --- |
| Bookmaker odds (de-vigged) | 0.954 | 0.565 | 55.2% |
| 50/50 blend | 0.963 | 0.571 | 53.9% |
| Elo → Poisson (this model) | 0.979 | 0.582 | 52.7% |

The market is (as expected) the strongest predictor. The value of the model is
that it predicts *any* future fixture months ahead, before odds exist, and its
gap to the market (~0.025 log loss) is in line with published academic models.
When pre-match odds are available, blending moves you toward the market.
Weather is attached to predictions as context; its measurable effect on
outcomes is negligible, which is why it stays out of the model.

## Honest limitations

- No squad-level information inside the core model: transfers, injuries,
  managerial changes and European fatigue are invisible to Elo until results
  reflect them. The `markets`, `squad` and `transfers` commands surface these
  signals, and `--market-implied` / `--squad-adjust` feed one of them back in.
- The `transfers` view lists players *new to La Liga* per club (valued by
  market price); intra-league moves are not itemised because no free
  last-season roster archive exists for La Liga.
- Head-to-head tiebreaks are applied once per group of level teams, not
  recursively for three-way-plus ties (negligible effect on probabilities).
- Expected points from simulation are compressed relative to a realized table
  (the eventual champion usually overperforms its pre-season expectation).
- The model cannot beat the betting market; treat outputs as calibrated
  probabilities, not an edge.
