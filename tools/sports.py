# tools/sports.py
import requests
import json
from datetime import datetime, timezone, timedelta

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
    """Devuelve True si la fecha UTC del evento corresponde al día de hoy en hora local."""
    if not event_date_utc:
        return False
    try:
        # La fecha viene en formato ISO 8601, ej.: "2025-05-07T19:00Z"
        event_dt = datetime.fromisoformat(event_date_utc.replace("Z", "+00:00"))
        now_utc = datetime.now(timezone.utc)
        # Comparar solo año, mes y día
        return event_dt.date() == now_utc.date()
    except:
        return False


def fetch_sports_data() -> tuple[list, dict]:
    """
    Retorna una tupla:
    - Lista de juegos procesados (priorizando los de hoy, hasta 5 partidos)
    - Diccionario de metadatos event_id -> info del evento
    """
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
                "is_today": _is_today(start_time)
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
    # Separar partidos de hoy y del futuro, ordenados por fecha
    today_games = [g for g in all_games if g["is_today"]]
    future_games = sorted(
        [g for g in all_games if not g["is_today"]],
        key=lambda g: g["start_time"]
    )
    # Construir lista final: hoy primero, luego próximos
    selected = today_games + future_games
    # Limitar a 5 partidos
    selected = selected[:5]
    # Filtrar events_meta a solo los seleccionados
    filtered_meta = {g["event_id"]: events_meta[g["event_id"]] for g in selected}
    return selected, filtered_meta


def build_sports_prompt(games_data: list) -> str:
    if not games_data:
        return "No se encontraron partidos programados para hoy ni para los próximos días en las ligas configuradas."

    today_candidates = [g for g in games_data if g.get("is_today")]
    future_candidates = [g for g in games_data if not g.get("is_today")]

    prompt = (
        "Eres un analista deportivo experto. Analiza los siguientes partidos "
        "y sugiere los equipos con mayores probabilidades de ganar.\n"
    )
    if today_candidates:
        prompt += f"Partidos de hoy ({len(today_candidates)}):\n"
    else:
        prompt += "No hay partidos programados para el día de hoy. Se muestran los próximos encuentros.\n"

    prompt += (
        "⚠️ IMPORTANTE: Devuelve tu respuesta **exclusivamente** en formato JSON, "
        "sin texto adicional fuera del JSON. El JSON debe tener la siguiente estructura:\n"
        '{"predictions": [{"game": "nombre del partido o resumen", "favorite": "nombre del equipo favorito"}]}\n'
        "No uses herramientas ni funciones. Responde solo con el JSON.\n\n"
    )

    for game in games_data:
        when = "HOY" if game.get("is_today") else "Próximamente"
        prompt += f"**{game['league']}** ({when}): {game['summary']} - {game.get('start_time', '')}\n"
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
    """
    Obtiene el resultado final de un evento usando el endpoint de resumen (summary).
    Retorna un diccionario con 'status' y 'winner', o None si el partido no ha terminado.
    """
    summary_url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={event_id}"
    try:
        resp = requests.get(summary_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        header = data.get("header", {})
        competitions = header.get("competitions", [])
        if not competitions:
            competitions = data.get("competitions", [])
        if not competitions:
            return None
        comp = competitions[0]
        status = comp.get("status", {}).get("type", {}).get("name", "")
        if "FINAL" not in status.upper() and "FINAL" not in status:
            return None
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