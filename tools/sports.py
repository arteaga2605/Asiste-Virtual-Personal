# tools/sports.py
import requests
import json
import unicodedata
import time
from datetime import datetime, timezone
from tools.mlb_stats import (
    get_probable_pitchers, get_pitcher_recent_stats,
    get_batter_vs_pitcher, get_team_streak,
    get_team_id_by_name, get_top_batters
)

SPORTS_CONFIG = [
    {"sport": "basketball", "league": "nba",     "name": "NBA",      "category": "basketball"},
    {"sport": "football",   "league": "nfl",     "name": "NFL",      "category": "football"},
    {"sport": "baseball",   "league": "mlb",     "name": "MLB",      "category": "baseball"},
    {"sport": "hockey",     "league": "nhl",     "name": "NHL",      "category": "hockey"},
    {"sport": "soccer",     "league": "eng.1",   "name": "Premier League",       "category": "soccer"},
    {"sport": "soccer",     "league": "esp.1",   "name": "La Liga",              "category": "soccer"},
    {"sport": "soccer",     "league": "ger.1",   "name": "Bundesliga",           "category": "soccer"},
    {"sport": "soccer",     "league": "ita.1",   "name": "Serie A",              "category": "soccer"},
    {"sport": "soccer",     "league": "fra.1",   "name": "Ligue 1",              "category": "soccer"},
    {"sport": "soccer",     "league": "ned.1",   "name": "Eredivisie",           "category": "soccer"},
    {"sport": "soccer",     "league": "sco.1",   "name": "Scottish Premiership", "category": "soccer"},
    {"sport": "soccer",     "league": "usa.1",   "name": "MLS",                  "category": "soccer"},
    {"sport": "soccer",     "league": "mex.1",   "name": "Liga MX",              "category": "soccer"},
    {"sport": "soccer",     "league": "ksa.1",   "name": "Saudi Pro League",     "category": "soccer"},
    {"sport": "soccer",     "league": "esp.w.1", "name": "Spanish Liga F",       "category": "soccer"},
    {"sport": "soccer",     "league": "aus.w.1", "name": "A-League Women",       "category": "soccer"},
]

ACTIVE_STATUSES = {
    "STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "STATUS_HALFTIME",
    "STATUS_END_PERIOD", "STATUS_RAIN_DELAY", "STATUS_SUSPENDED",
}

BASE_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
BASE_EVENT_URL = "https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/events/{event_id}/competitions/{event_id}"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={event_id}"

_espn_available = True

def is_espn_available() -> bool:
    return _espn_available

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    return text

def get_today_scoreboard(sport: str, league: str) -> list:
    global _espn_available
    url = BASE_SCOREBOARD_URL.format(sport=sport, league=league)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _espn_available = True
        return data.get("events", [])
    except Exception as e:
        print(f"Error obteniendo scoreboard {sport}/{league}: {e}")
        _espn_available = False
        return []

def get_event_odds(sport: str, league: str, event_id: str) -> dict | None:
    url = BASE_EVENT_URL.format(sport=sport, league=league, event_id=event_id) + "/odds"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error obteniendo odds evento {event_id}: {e}")
        return None

def parse_odds_data(odds_data: dict) -> str | None:
    if not odds_data or "items" not in odds_data:
        return None
    details_list = []
    for item in odds_data.get("items", []):
        provider = item.get("provider", {}).get("name", "Desconocido")
        details = item.get("details")
        if details:
            details_list.append(f"{provider}: {details}")
        elif "spread" in item:
            details_list.append(f"{provider}: spread {item['spread']}")
    return "; ".join(details_list) if details_list else None

def _event_is_active(event: dict) -> bool:
    status_type = event.get("status", {}).get("type", {})
    status_name = status_type.get("name", "")
    short = status_type.get("shortDetail", "")
    if status_name in ACTIVE_STATUSES:
        return True
    if "Final" in short or "final" in short:
        return False
    return True

def _is_today(event_date_utc):
    if not event_date_utc:
        return False
    try:
        event_dt = datetime.fromisoformat(event_date_utc.replace("Z", "+00:00"))
        now_utc = datetime.now(timezone.utc)
        return event_dt.date() == now_utc.date()
    except:
        return False

def _get_detailed_stats(sport: str, league: str, event_id: str) -> dict:
    url = SUMMARY_URL.format(sport=sport, league=league, event_id=event_id)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error obteniendo summary para {event_id}: {e}")
        return {}
    boxscore = data.get("boxscore", {})
    teams_stats = boxscore.get("teams", [])
    stats_dict = {}
    for team in teams_stats:
        team_name = team.get("team", {}).get("displayName", "Desconocido")
        statistics_list = team.get("statistics", [])
        stats_summary = {}
        for stat in statistics_list:
            name = stat.get("name", stat.get("label", "otro"))
            display_val = stat.get("displayValue", stat.get("value", ""))
            if display_val and display_val != "":
                stats_summary[name] = display_val
        stats_dict[team_name] = stats_summary
    return stats_dict

def enrich_games_with_stats(games: list) -> list:
    for game in games:
        sport = game.get("sport")
        league = game.get("league_slug")
        event_id = game.get("event_id")
        if sport and league and event_id:
            stats = _get_detailed_stats(sport, league, event_id)
            game["detailed_stats"] = stats
        else:
            game["detailed_stats"] = {}
    return games

def _enrich_mlb_pitchers(game: dict):
    """Para un partido de MLB, obtiene pitchers, rachas y enfrentamientos."""
    if game.get("sport") != "baseball" or game.get("league_slug") != "mlb":
        return
    event_id = game.get("event_id")
    if not event_id:
        return

    # Pitchers probables
    pitchers = get_probable_pitchers(event_id)
    game["probable_pitchers"] = pitchers

    # Estadísticas recientes de cada pitcher
    pitcher_stats = []
    for p in pitchers:
        pid = p.get("id")
        if pid:
            stats = get_pitcher_recent_stats(pid)
            if stats:
                pitcher_stats.append({**p, "recent": stats})
        time.sleep(0.1)
    game["pitcher_stats"] = pitcher_stats

    # Rachas de equipos
    team_streaks = {}
    for team in game.get("teams", []):
        team_name = team.get("name")
        if team_name:
            tid = get_team_id_by_name(team_name)
            if tid:
                streak = get_team_streak(tid)
                if streak:
                    team_streaks[team_name] = streak
            time.sleep(0.1)
    game["team_streaks"] = team_streaks

    # Enfrentamientos bateador-pitcher (top 3 bateadores de cada equipo contra el pitcher rival)
    batter_vs_pitcher = []
    # Solo si tenemos al menos un pitcher con ID
    for p in pitcher_stats:
        pitcher_id = p.get("id")
        pitcher_name = p.get("name")
        # Para cada equipo, obtener top 3 bateadores
        for team in game.get("teams", []):
            team_name = team.get("name")
            # Evitar consultar al pitcher de su propio equipo
            if team_name == p.get("team"):
                continue
            top_batters = get_top_batters(team_name, limit=3)
            for batter in top_batters:
                bvp = get_batter_vs_pitcher(batter["id"], pitcher_id)
                if bvp and bvp.get("atBats", 0) > 0:
                    batter_vs_pitcher.append({
                        "batter": batter["name"],
                        "pitcher": pitcher_name,
                        "avg": bvp.get("avg"),
                        "hits": bvp.get("hits", 0),
                        "atBats": bvp.get("atBats", 0),
                        "homeRuns": bvp.get("homeRuns", 0),
                        "strikeOuts": bvp.get("strikeOuts", 0)
                    })
                time.sleep(0.1)
    game["batter_vs_pitcher"] = batter_vs_pitcher

def fetch_sports_data(category_filter: str = None) -> tuple[list, dict]:
    all_games = []
    events_meta = {}
    configs = SPORTS_CONFIG
    if category_filter:
        configs = [c for c in SPORTS_CONFIG if c.get("category") == category_filter]
    for config in configs:
        events = get_today_scoreboard(config["sport"], config["league"])
        for event in events:
            if not _event_is_active(event):
                continue
            event_id = event["id"]
            start_time = event.get("date", "")
            status_name = event.get("status", {}).get("type", {}).get("name", "Desconocido")
            game_info = {
                "league": config["name"], "status": status_name, "teams": [],
                "odds": None, "start_time": start_time,
                "summary": event.get("shortName", ""), "event_id": event_id,
                "sport": config["sport"], "league_slug": config["league"],
                "is_today": _is_today(start_time), "detailed_stats": {}
            }
            competitions = event.get("competitions", [])
            for comp in competitions:
                for competitor in comp.get("competitors", []):
                    team = {
                        "name": competitor.get("team", {}).get("displayName"),
                        "abbreviation": competitor.get("team", {}).get("abbreviation"),
                        "homeAway": competitor.get("homeAway", ""),
                        "score": competitor.get("score"),
                        "record": competitor.get("records", [{}])[0].get("summary") if competitor.get("records") else None
                    }
                    game_info["teams"].append(team)
                odds = get_event_odds(config["sport"], config["league"], event_id)
                if odds:
                    game_info["odds"] = parse_odds_data(odds)
            if game_info["teams"]:
                all_games.append(game_info)
                events_meta[event_id] = {
                    "league": config["name"],
                    "teams": [t["name"] for t in game_info["teams"]],
                    "abbreviations": [t.get("abbreviation", "") for t in game_info["teams"]],
                    "start_time": start_time,
                    "summary": game_info["summary"],
                    "sport": config["sport"],
                    "league_slug": config["league"],
                }
    # Enriquecer partidos MLB con datos de pitchers, rachas y enfrentamientos
    for game in all_games:
        if game.get("sport") == "baseball" and game.get("league_slug") == "mlb":
            _enrich_mlb_pitchers(game)

    today_games = [g for g in all_games if g["is_today"]]
    future_games = sorted([g for g in all_games if not g["is_today"]], key=lambda g: g["start_time"])
    selected = today_games + future_games
    selected = selected[:5]
    selected = enrich_games_with_stats(selected)
    filtered_meta = {g["event_id"]: events_meta[g["event_id"]] for g in selected if g["event_id"] in events_meta}
    return selected, filtered_meta

def build_sports_prompt(games_data: list) -> str:
    if not games_data:
        return "No se encontraron partidos programados para hoy ni para los próximos días en las ligas configuradas."
    today_candidates = [g for g in games_data if g.get("is_today")]
    future_candidates = [g for g in games_data if not g.get("is_today")]
    prompt = (
        "Eres un analista deportivo experto. Analiza los siguientes partidos "
        "y sugiere los equipos con mayores probabilidades de ganar, **incluyendo el marcador estimado "
        "y un intervalo de confianza (porcentaje)**.\n"
    )
    if today_candidates:
        prompt += f"Partidos de hoy ({len(today_candidates)}):\n"
    else:
        prompt += "No hay partidos programados para el día de hoy. Se muestran los próximos encuentros.\n"
    prompt += (
        "⚠️ **INSTRUCCIÓN ESTRICTA**:\n"
        "- Devuelve **exactamente** un JSON válido y nada más.\n"
        "- La lista 'predictions' debe tener **un elemento por cada partido**, nunca vacía.\n"
        "- **IMPORTANTE**: Para el campo 'favorite' usa **SIEMPRE el nombre completo del equipo** tal como aparece en los datos "
        "(ej. 'Manchester City', NO 'MNC' ni 'City').\n"
        "- El formato debe ser:\n"
        '{"predictions": [{"game": "RESUMEN EXACTO DEL PARTIDO", "favorite": "nombre completo del equipo", '
        '"score": "marcador estimado (ej. 3-2)", "confidence": número entre 0 y 100}]}\n'
        "Usa exactamente el RESUMEN que aparece en cada partido para el campo 'game'.\n\n"
    )
    for game in games_data:
        when = "HOY" if game.get("is_today") else "Próximamente"
        team_names = []
        for team in game["teams"]:
            tag = " (Casa)" if team.get("homeAway") == "home" else " (Fuera)" if team.get("homeAway") == "away" else ""
            team_names.append(f"{team['name']}{tag}")
        teams_line = " vs ".join(team_names)
        prompt += f"**{game['league']}** ({when}): {teams_line} - {game.get('start_time', '')}\n"
        prompt += f"RESUMEN: {game['summary']}\n"
        prompt += f"Estado: {game['status']}\n"
        for team in game["teams"]:
            record = f" ({team['record']})" if team.get("record") else ""
            prompt += f"  - {team['name']}: {team.get('score', 'N/A')}{record}\n"
        if game.get("odds"):
            prompt += f"Cuotas: {game['odds']}\n"
        detailed = game.get("detailed_stats", {})
        if detailed:
            prompt += "Estadísticas avanzadas:\n"
            for team_name, stats in detailed.items():
                if stats:
                    stat_str = ", ".join([f"{k}: {v}" for k, v in stats.items()])
                    prompt += f"  {team_name}: {stat_str}\n"
        # Sección MLB
        if game.get("sport") == "baseball" and game.get("league_slug") == "mlb":
            pitchers = game.get("pitcher_stats", [])
            if pitchers:
                prompt += "**Lanzadores probables y su forma reciente (últimas 5 salidas):**\n"
                for p in pitchers:
                    recent = p.get("recent", {})
                    if recent:
                        prompt += f"  - {p['name']} ({p.get('team', '')}): {recent.get('wins',0)}-{recent.get('losses',0)}, ERA {recent.get('era','N/D')}, {recent.get('innings','N/D')} IP\n"
                    else:
                        prompt += f"  - {p['name']} ({p.get('team', '')}): sin datos recientes\n"
                prompt += "\n"
            batter_vs = game.get("batter_vs_pitcher", [])
            if batter_vs:
                prompt += "**Enfrentamientos bateador-pitcher destacados:**\n"
                for bvp in batter_vs:
                    avg_str = f"{float(bvp['avg']):.3f}" if bvp.get('avg') is not None else "N/D"
                    prompt += f"  - {bvp['batter']} vs {bvp['pitcher']}: AVG {avg_str}, {bvp.get('hits',0)} H, {bvp.get('homeRuns',0)} HR, {bvp.get('strikeOuts',0)} K en {bvp.get('atBats',0)} VB\n"
                prompt += "\n"
            streaks = game.get("team_streaks", {})
            if streaks:
                prompt += "**Rachas recientes de equipos:**\n"
                for team_name, streak in streaks.items():
                    prompt += f"  - {team_name}: {streak}\n"
                prompt += "\n"
        prompt += "\n"
    prompt += "Genera ahora el JSON con las predicciones (un elemento por partido, con confianza)."
    return prompt

def get_event_result(sport: str, league: str, event_id: str, retries: int = 2) -> dict | None:
    summary_url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={event_id}"
    last_exception = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(summary_url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            header = data.get("header", {})
            competitions = header.get("competitions", [])
            if not competitions:
                competitions = data.get("competitions", [])
            if not competitions:
                return None
            comp = competitions[0]
            status_info = comp.get("status", {})
            completed = status_info.get("type", {}).get("completed", False)
            if not completed:
                status_name = status_info.get("type", {}).get("name", "").upper()
                if "FINAL" not in status_name and "FULL_TIME" not in status_name and "COMPLETE" not in status_name:
                    return None
            competitors = comp.get("competitors", [])
            winner = None
            for c in competitors:
                if c.get("winner"):
                    winner = c.get("team", {}).get("displayName")
                    break
            if not winner and len(competitors) == 2:
                scores = []
                for c in competitors:
                    score_str = c.get("score", "0")
                    try:
                        scores.append(int(float(score_str)))
                    except:
                        scores.append(0)
                if scores[0] != scores[1]:
                    winner_idx = 0 if scores[0] > scores[1] else 1
                    winner = competitors[winner_idx].get("team", {}).get("displayName")
            return {"status": status_info.get("type", {}).get("name", "Desconocido"), "winner": winner}
        except Exception as e:
            last_exception = e
            if attempt < retries:
                time.sleep(2)
            else:
                print(f"Error obteniendo summary para resultado de {event_id} (tras {retries} reintentos): {e}")
    return None