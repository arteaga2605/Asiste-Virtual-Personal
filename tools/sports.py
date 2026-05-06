# tools/sports.py
import requests

# Solo las 4 grandes ligas de EE.UU. (más rápidas de obtener y menos datos)
SPORTS_CONFIG = [
    {"sport": "basketball", "league": "nba", "name": "NBA"},
    {"sport": "football",   "league": "nfl", "name": "NFL"},
    {"sport": "baseball",   "league": "mlb", "name": "MLB"},
    {"sport": "hockey",     "league": "nhl", "name": "NHL"},
]

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


def fetch_sports_data() -> list:
    all_games = []
    for config in SPORTS_CONFIG:
        events = get_today_scoreboard(config["sport"], config["league"])
        for event in events:
            game_info = {
                "league": config["name"],
                "status": event.get("status", {}).get("type", {}).get("name", "Desconocido"),
                "teams": [],
                "odds": None,
                "start_time": event.get("date", ""),
                "summary": event.get("shortName", "")
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
                odds = get_event_odds(config["sport"], config["league"], event["id"])
                if odds:
                    game_info["odds"] = parse_odds_data(odds)
            if game_info["teams"]:
                all_games.append(game_info)
    return all_games


def build_sports_prompt(games_data: list) -> str:
    if not games_data:
        return "No se encontraron partidos programados para hoy en las ligas configuradas."

    # Limitar a 5 partidos para que el prompt no sea enorme
    if len(games_data) > 5:
        games_data = games_data[:5]

    prompt = (
        "Eres un analista deportivo experto. Analiza los siguientes partidos del día "
        "y sugiere los equipos con mayores probabilidades de ganar.\n"
        "⚠️ IMPORTANTE: NO uses herramientas ni funciones. Responde solo con texto.\n\n"
    )

    for game in games_data:
        prompt += f"**{game['league']}**: {game['summary']} - {game.get('start_time', 'Hora no disponible')}\n"
        prompt += f"Estado: {game['status']}\n"
        for team in game["teams"]:
            record = f" ({team['record']})" if team.get("record") else ""
            prompt += f"  - {team['name']} ({team.get('homeAway', 'N/A')}) {team.get('score', '')}{record}\n"
        if game.get("odds"):
            prompt += f"Cuotas: {game['odds']}\n"
        prompt += "\n"

    prompt += "Indica para cada partido el equipo favorito y una breve razón. Sé conciso."
    return prompt