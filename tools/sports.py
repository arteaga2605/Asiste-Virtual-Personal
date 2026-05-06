# tools/sports.py
import requests
import json

SPORTS_CONFIG = [
    # Grandes ligas de EE.UU.
    {"sport": "basketball", "league": "nba",     "name": "NBA"},
    {"sport": "football",   "league": "nfl",     "name": "NFL"},
    {"sport": "baseball",   "league": "mlb",     "name": "MLB"},
    {"sport": "hockey",     "league": "nhl",     "name": "NHL"},
    # Fútbol masculino europeo
    {"sport": "soccer",     "league": "eng.1",   "name": "Premier League"},
    {"sport": "soccer",     "league": "fra.1",   "name": "Ligue 1"},
    {"sport": "soccer",     "league": "ned.1",   "name": "Eredivisie"},
    {"sport": "soccer",     "league": "sco.1",   "name": "Scottish Premiership"},
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


def fetch_sports_data() -> tuple[list, dict]:
    """
    Retorna una tupla:
    - Lista de juegos procesados (para el prompt)
    - Diccionario de metadatos: event_id -> info del evento (para guardar predicciones)
    """
    all_games = []
    events_meta = {}
    for config in SPORTS_CONFIG:
        events = get_today_scoreboard(config["sport"], config["league"])
        for event in events:
            if not _event_is_active(event):
                continue

            event_id = event["id"]
            game_info = {
                "league": config["name"],
                "status": event.get("status", {}).get("type", {}).get("name", "Desconocido"),
                "teams": [],
                "odds": None,
                "start_time": event.get("date", ""),
                "summary": event.get("shortName", ""),
                "event_id": event_id,
                "sport": config["sport"],
                "league_slug": config["league"],
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
                    "start_time": game_info["start_time"],
                    "summary": game_info["summary"],
                    "sport": config["sport"],
                    "league_slug": config["league"],
                }
    return all_games, events_meta


def build_sports_prompt(games_data: list) -> str:
    if not games_data:
        return "No se encontraron partidos programados para hoy en las ligas configuradas."

    if len(games_data) > 5:
        games_data = games_data[:5]

    prompt = (
        "Eres un analista deportivo experto. Analiza los siguientes partidos del día "
        "y sugiere los equipos con mayores probabilidades de ganar.\n"
        "⚠️ IMPORTANTE: Devuelve tu respuesta **exclusivamente** en formato JSON, "
        "sin texto adicional fuera del JSON. El JSON debe tener la siguiente estructura:\n"
        '{"predictions": [{"game": "nombre del partido o resumen", "favorite": "nombre del equipo favorito"}]}\n'
        "No uses herramientas ni funciones. Responde solo con el JSON.\n\n"
    )

    for game in games_data:
        prompt += f"**{game['league']}**: {game['summary']} (ID: {game['event_id']}) - {game.get('start_time', '')}\n"
        prompt += f"Estado: {game['status']}\n"
        for team in game["teams"]:
            record = f" ({team['record']})" if team.get("record") else ""
            prompt += f"  - {team['name']} ({team.get('homeAway', 'N/A')}) {team.get('score', '')}{record}\n"
        if game.get("odds"):
            prompt += f"Cuotas: {game['odds']}\n"
        prompt += "\n"

    prompt += "Proporciona el JSON con las predicciones para estos partidos."
    return prompt


def get_event_result(sport: str, league: str, event_id: str) -> dict | None:
    """Obtiene el resultado final de un evento (ganador)."""
    url = BASE_EVENT_URL.format(sport=sport, league=league, event_id=event_id)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        comps = data.get("competitions", [])
        if not comps:
            return None
        comp = comps[0]
        status = comp.get("status", {}).get("type", {}).get("name", "")
        if "FINAL" not in status and "Final" not in status:
            return None  # partido no terminado
        competitors = comp.get("competitors", [])
        winner = None
        for c in competitors:
            if c.get("winner"):
                winner = c.get("team", {}).get("displayName")
                break
        return {"status": status, "winner": winner}
    except Exception as e:
        print(f"Error obteniendo resultado para {event_id}: {e}")
        return None