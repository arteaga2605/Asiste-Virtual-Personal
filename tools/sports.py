# tools/sports.py
import requests
import json
from datetime import datetime, timezone

SPORTS_CONFIG = [
    # Grandes ligas de EE.UU.
    {"sport": "basketball", "league": "nba",     "name": "NBA"},
    {"sport": "football",   "league": "nfl",     "name": "NFL"},
    {"sport": "baseball",   "league": "mlb",     "name": "MLB"},
    {"sport": "hockey",     "league": "nhl",     "name": "NHL"},
    # Fútbol masculino europeo
    {"sport": "soccer",     "league": "eng.1",   "name": "Premier League"},
    {"sport": "soccer",     "league": "esp.1",   "name": "La Liga"},
    {"sport": "soccer",     "league": "ger.1",   "name": "Bundesliga"},
    {"sport": "soccer",     "league": "ita.1",   "name": "Serie A"},
    {"sport": "soccer",     "league": "fra.1",   "name": "Ligue 1"},
    {"sport": "soccer",     "league": "ned.1",   "name": "Eredivisie"},
    {"sport": "soccer",     "league": "sco.1",   "name": "Scottish Premiership"},
    # Fútbol americano e internacional
    {"sport": "soccer",     "league": "usa.1",   "name": "MLS"},
    {"sport": "soccer",     "league": "mex.1",   "name": "Liga MX"},
    # Fútbol de otras regiones
    {"sport": "soccer",     "league": "ksa.1",   "name": "Saudi Pro League"},
    # Fútbol femenino
    {"sport": "soccer",     "league": "esp.w.1", "name": "Spanish Liga F"},
    {"sport": "soccer",     "league": "aus.w.1", "name": "A-League Women"},
]

ACTIVE_STATUSES = {
    "STATUS_SCHEDULED",
    "STATUS_IN_PROGRESS",
    "STATUS_HALFTIME",
    "STATUS_END_PERIOD",
    "STATUS_RAIN_DELAY",
    "STATUS_SUSPENDED",
}

BASE_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
BASE_EVENT_URL = "https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/events/{event_id}/competitions/{event_id}"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={event_id}"


def get_today_scoreboard(sport: str, league: str) -> list:
    url = BASE_SCOREBOARD_URL.format(sport=sport, league=league)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("events", [])
    except Exception as e:
        print(f"Error obteniendo scoreboard {sport}/{league}: {e}")
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
            name = stat.get("name", "otro")
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


def fetch_sports_data() -> tuple[list, dict]:
    all_games = []
    events_meta = {}
    for config in SPORTS_CONFIG:
        events = get_today_scoreboard(config["sport"], config["league"])
        for event in events:
            if not _event_is_active(event):
                continue

            event_id = event["id"]
            start_time = event.get("date", "")
            status_name = event.get("status", {}).get("type", {}).get("name", "Desconocido")
            game_info = {
                "league": config["name"],
                "status": status_name,
                "teams": [],
                "odds": None,
                "start_time": start_time,
                "summary": event.get("shortName", ""),
                "event_id": event_id,
                "sport": config["sport"],
                "league_slug": config["league"],
                "is_today": _is_today(start_time),
                "detailed_stats": {}
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
    today_games = [g for g in all_games if g["is_today"]]
    future_games = sorted(
        [g for g in all_games if not g["is_today"]],
        key=lambda g: g["start_time"]
    )
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
        "y sugiere los equipos con mayores probabilidades de ganar, **incluyendo el marcador estimado**.\n"
    )
    if today_candidates:
        prompt += f"Partidos de hoy ({len(today_candidates)}):\n"
    else:
        prompt += "No hay partidos programados para el día de hoy. Se muestran los próximos encuentros.\n"

    prompt += (
        "⚠️ IMPORTANTE: Devuelve tu respuesta **exclusivamente** en formato JSON, "
        "sin texto adicional fuera del JSON. El JSON debe tener la siguiente estructura:\n"
        '{"predictions": [{"game": "nombre del partido o resumen", "favorite": "nombre del equipo favorito", "score": "marcador estimado (ej. 3-2)"}]}\n'
        "No uses herramientas ni funciones. Responde solo con el JSON.\n\n"
    )

    for game in games_data:
        when = "HOY" if game.get("is_today") else "Próximamente"
        team_names = []
        for team in game["teams"]:
            tag = " (Casa)" if team.get("homeAway") == "home" else " (Fuera)" if team.get("homeAway") == "away" else ""
            team_names.append(f"{team['name']}{tag}")
        teams_line = " vs ".join(team_names)

        prompt += f"**{game['league']}** ({when}): {teams_line} - {game.get('start_time', '')}\n"
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
        prompt += "\n"

    prompt += "Proporciona el JSON con las predicciones para estos partidos."
    return prompt


def get_event_result(sport: str, league: str, event_id: str) -> dict | None:
    """
    Obtiene el resultado final de un evento.
    Ahora se basa en el campo 'completed' del summary y extrae el ganador de forma robusta.
    """
    summary_url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={event_id}"
    try:
        resp = requests.get(summary_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error obteniendo summary para resultado de {event_id}: {e}")
        return None

    # Obtener la competición principal
    header = data.get("header", {})
    competitions = header.get("competitions", [])
    if not competitions:
        competitions = data.get("competitions", [])
    if not competitions:
        return None

    comp = competitions[0]
    status_info = comp.get("status", {})
    # Comprobar si el evento está completado usando el booleano 'completed'
    completed = status_info.get("type", {}).get("completed", False)
    if not completed:
        # También podemos revisar el nombre del estado por si acaso
        status_name = status_info.get("type", {}).get("name", "").upper()
        if "FINAL" not in status_name and "FULL_TIME" not in status_name and "COMPLETE" not in status_name:
            return None  # No finalizado

    # Extraer los competidores
    competitors = comp.get("competitors", [])
    winner = None

    # Buscar el ganador explícito
    for c in competitors:
        if c.get("winner"):
            winner = c.get("team", {}).get("displayName")
            break

    # Si no hay ganador explícito, decidir por marcador
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