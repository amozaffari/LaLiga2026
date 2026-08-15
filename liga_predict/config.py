"""Central configuration: seasons, team-name canonicalisation, stadium coordinates."""

import re
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OUT_DIR = PROJECT_ROOT / "output"

# football-data.co.uk season codes, oldest first. "0001" -> 2000-01.
# Includes the in-progress season; its file 404s until the first matches are played.
SEASONS = [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(2000, 2027)]
UPCOMING_SEASON = SEASONS[-1]  # the season being predicted (2026-27)
SEASON_LABEL = "2026-27"
DIVISIONS = ["SP1", "SP2"]  # La Liga (Primera División), Segunda División
TOP_DIV, SECOND_DIV = DIVISIONS

FOOTBALL_DATA_URL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
# ESPN's public scoreboard: one call returns the whole season with UTC kickoffs,
# live status and scores. Two hosts serve the same API; the first is sometimes
# geo-blocked by ESPN's CDN, so both are tried.
ESPN_SCOREBOARD_URLS = [
    "https://site.web.api.espn.com/apis/site/v2/sports/soccer/esp.1/scoreboard",
    "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/scoreboard",
]
ESPN_SEASON_DATES = "20260801-20270630"
# Community fixture feed: has the official matchday (round) numbers that ESPN lacks.
FIXTUREDOWNLOAD_URL = "https://fixturedownload.com/feed/json/la-liga-2026"
# Biwenger (Spanish fantasy game) public competition data: every La Liga player
# with points, last-season points, market price, injury/suspension status.
BIWENGER_URL = "https://cf.biwenger.com/api/v2/competitions/la-liga/data"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 liga-predict/1.0")

# ---------------------------------------------------------------------------
# Team names. Every data source spells clubs differently (football-data says
# "Ath Bilbao", ESPN "Athletic Club", Polymarket "Athletic Bilbao", Biwenger
# "Athletic"). Everything downstream uses the canonical display name; sources
# are translated on load through `canonical_team`.
# ---------------------------------------------------------------------------
TEAMS_2026_27 = [
    "Alavés", "Athletic Club", "Atlético Madrid", "Barcelona", "Celta Vigo",
    "Deportivo", "Elche", "Espanyol", "Getafe", "Levante", "Málaga", "Osasuna",
    "Racing Santander", "Rayo Vallecano", "Real Betis", "Real Madrid",
    "Real Sociedad", "Sevilla", "Valencia", "Villarreal",
]

# canonical -> aliases seen across football-data, ESPN, fixturedownload,
# Polymarket, Biwenger and The Odds API. Matching is accent/case-insensitive.
_ALIASES = {
    "Alavés": ["Alaves", "Deportivo Alavés", "Deportivo Alaves", "CD Alavés"],
    "Athletic Club": ["Ath Bilbao", "Athletic Bilbao", "Athletic", "Athletic de Bilbao"],
    "Atlético Madrid": ["Ath Madrid", "Atlético de Madrid", "Atletico Madrid",
                        "Atlético", "Club Atlético de Madrid", "Atletico de Madrid"],
    "Barcelona": ["FC Barcelona", "Barça"],
    "Celta Vigo": ["Celta", "RC Celta", "RC Celta de Vigo", "Celta de Vigo"],
    "Deportivo": ["La Coruna", "RC Deportivo", "Deportivo La Coruña",
                  "Deportivo de A Coruña", "RC Deportivo A Coruña", "Deportivo La Coruna",
                  "RC Deportivo La Coruña", "Depor"],
    "Elche": ["Elche CF"],
    "Espanyol": ["Espanol", "RCD Espanyol", "RCD Espanyol de Barcelona"],
    "Getafe": ["Getafe CF"],
    "Levante": ["Levante UD"],
    "Málaga": ["Malaga", "Málaga CF", "Malaga CF"],
    "Osasuna": ["CA Osasuna"],
    "Racing Santander": ["Santander", "Racing", "R. Racing Club", "Real Racing Club",
                         "Racing de Santander", "Real Racing Club de Santander",
                         "Racing Club"],
    "Rayo Vallecano": ["Vallecano", "Rayo", "Rayo Vallecano de Madrid"],
    "Real Betis": ["Betis", "Real Betis Balompié", "Real Betis Balompie"],
    "Real Madrid": ["Real Madrid CF"],
    "Real Sociedad": ["Sociedad", "Real Sociedad de Fútbol", "Real Sociedad de Futbol"],
    "Sevilla": ["Sevilla FC"],
    "Valencia": ["Valencia CF"],
    "Villarreal": ["Villarreal CF"],
    # Frequent SP1/SP2 clubs whose football-data spelling deserves a display name.
    "Girona": ["Girona FC"],
    "Mallorca": ["RCD Mallorca", "Real Mallorca"],
    "Real Oviedo": ["Oviedo"],
    "Las Palmas": ["UD Las Palmas"],
    "Valladolid": ["Real Valladolid"],
    "Leganés": ["Leganes", "CD Leganés"],
    "Cádiz": ["Cadiz", "Cádiz CF"],
    "Almería": ["Almeria", "UD Almería"],
    "Granada": ["Granada CF"],
    "Sporting Gijón": ["Sp Gijon", "Sporting Gijon", "Real Sporting"],
    "Zaragoza": ["Real Zaragoza"],
    "Eibar": ["SD Eibar"],
    "Huesca": ["SD Huesca"],
    "Córdoba": ["Cordoba", "Córdoba CF"],
    "Castellón": ["Castellon", "CD Castellón"],
    "Mirandés": ["Mirandes", "CD Mirandés"],
    "Cultural Leonesa": ["Cultural", "Leonesa"],
    "Albacete": ["Albacete Balompié"],
    "Burgos": ["Burgos CF"],
    "Tenerife": ["CD Tenerife"],
    "Alcorcón": ["Alcorcon", "AD Alcorcón"],
    "Ponferradina": ["SD Ponferradina"],
    "Lugo": ["CD Lugo"],
    "Numancia": ["CD Numancia"],
    "Gimnàstic": ["Gimnastic", "Nàstic"],
    "Reus": ["CF Reus"],
    "Extremadura": ["Extremadura UD"],
    "Fuenlabrada": ["CF Fuenlabrada"],
    "Sabadell": ["CE Sabadell"],
    "Logroñés": ["Logrones", "UD Logroñés"],
    "Amorebieta": ["SD Amorebieta"],
    "Ibiza": ["UD Ibiza"],
    "Andorra": ["FC Andorra"],
    "Eldense": ["CD Eldense"],
    "Cartagena": ["FC Cartagena"],
    "Ceuta": ["AD Ceuta"],
    "Real Sociedad B": ["Sociedad B", "Sanse"],
    "Recreativo": ["Recreativo Huelva"],
    "Hércules": ["Hercules", "Hércules CF"],
    "Xerez": ["Xerez CD"],
    "Murcia": ["Real Murcia"],
    "Salamanca": ["UD Salamanca"],
    "Alavés B": ["Alaves B"],
    "Barcelona B": ["Barcelona B", "Barça B"],
    "Real Madrid B": ["Real Madrid B", "Castilla"],
    "Sevilla B": ["Sevilla B"],
    "Villarreal B": ["Villarreal B"],
    "Bilbao Athletic": ["Ath Bilbao B", "Athletic B"],
    "Elche B": ["Elche B"],
    "Polideportivo Ejido": ["Ejido", "Poli Ejido"],
    "Ciudad de Murcia": ["Ciudad de Murcia"],
    "Terrassa": ["Terrassa FC"],
    "Getafe B": ["Getafe B"],
    "Girona B": ["Girona B"],
    "Badajoz": ["CD Badajoz"],
    "Compostela": ["SD Compostela"],
    "Universidad Las Palmas": ["Univ Las Palmas"],
    "Vecindario": ["Vecindario"],
    "Lorca": ["Lorca Deportiva", "Lorca FC"],
    "Racing Ferrol": ["Ferrol", "Racing de Ferrol"],
    "Éibar B": ["Eibar B"],
    "Llagostera": ["Llagostera"],
    "Alcoyano": ["CD Alcoyano"],
    "Guadalajara": ["CD Guadalajara"],
    "Xerez Deportivo": ["Xerez Deportivo"],
    "Jaén": ["Jaen", "Real Jaén"],
    "Mérida": ["Merida", "AD Mérida"],
    "Osasuna B": ["Osasuna B"],
    "Celta B": ["Celta B"],
    "Valencia B": ["Valencia B", "Mestalla"],
    "Rayo Majadahonda": ["Rayo Majadahonda"],
}


def _norm(name: str) -> str:
    """Accent- and case-insensitive key: 'Atlético de Madrid' -> 'atletico de madrid'."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


_LOOKUP: dict[str, str] = {}
for _canon, _aliases in _ALIASES.items():
    _LOOKUP[_norm(_canon)] = _canon
    for _a in _aliases:
        _LOOKUP.setdefault(_norm(_a), _canon)


def canonical_team(name: str) -> str:
    """Map any source's spelling of a club to the canonical display name.

    Unknown names pass through unchanged (historic clubs only need to be
    self-consistent inside football-data, which they are).
    """
    if name is None:
        return name
    key = _norm(name)
    if key in _LOOKUP:
        return _LOOKUP[key]
    # Common suffix/prefix noise: "X CF", "X FC", "UD X", "SD X", "CD X", "RCD X".
    stripped = re.sub(r"\b(cf|fc|ud|sd|cd|rcd|rc|ca|ad|ce|club|de)\b", " ", key).strip()
    stripped = re.sub(r"\s+", " ", stripped)
    if stripped in _LOOKUP:
        return _LOOKUP[stripped]
    return str(name).strip()


# Approximate stadium coordinates for the 2026-27 clubs (for weather lookups).
STADIUMS = {
    "Alavés": (42.8371, -2.6880),          # Mendizorroza, Vitoria-Gasteiz
    "Athletic Club": (43.2641, -2.9494),   # San Mamés, Bilbao
    "Atlético Madrid": (40.4362, -3.5995),  # Metropolitano, Madrid
    "Barcelona": (41.3809, 2.1228),        # Camp Nou
    "Celta Vigo": (42.2119, -8.7397),      # Balaídos, Vigo
    "Deportivo": (43.3687, -8.4176),       # Riazor, A Coruña
    "Elche": (38.2669, -0.6613),           # Martínez Valero
    "Espanyol": (41.3478, 2.0757),         # RCDE Stadium, Cornellà
    "Getafe": (40.3256, -3.7146),          # Coliseum
    "Levante": (39.4948, -0.3636),         # Ciutat de València
    "Málaga": (36.7340, -4.4267),          # La Rosaleda
    "Osasuna": (42.7967, -1.6369),         # El Sadar, Pamplona
    "Racing Santander": (43.4744, -3.7960),  # El Sardinero
    "Rayo Vallecano": (40.3919, -3.6588),  # Vallecas, Madrid
    "Real Betis": (37.4405, -5.9852),      # La Cartuja (Villamarín being rebuilt)
    "Real Madrid": (40.4531, -3.6883),     # Bernabéu
    "Real Sociedad": (43.3014, -1.9736),   # Anoeta, San Sebastián
    "Sevilla": (37.3840, -5.9705),         # Sánchez-Pizjuán
    "Valencia": (39.4747, -0.3583),        # Mestalla
    "Villarreal": (39.9441, -0.1035),      # La Cerámica
}
