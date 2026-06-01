# tools/mlb_stats.py
import requests
import time
from datetime import datetime

def _get_json(url, timeout=10):
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error consultando {url}: {e}")
        return None

def get_pitcher_recent_stats(pitcher_id: int) -> dict:
    current_year = datetime.now().year
    url = (f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}/stats"
           f"?stats=gameLog&season={current_year}&group=pitching&gameType=R")
    data = _get_json(url)
    if not data or "stats" not in data:
        return None
    stats = data["stats"]
    if not stats:
        return None
    splits = stats[0].get("splits", [])
    if not splits:
        return None
    recent = splits[:5]
    wins = sum(1 for g in recent if g.get("stat", {}).get("wins", 0) == 1)
    losses = sum(1 for g in recent if g.get("stat", {}).get("losses", 0) == 1)
    era = sum(g.get("stat", {}).get("era", 0) for g in recent) / len(recent) if recent else 0
    innings = sum(g.get("stat", {}).get("inningsPitched", 0) for g in recent)
    return {
        "wins": wins,
        "losses": losses,
        "era": round(era, 2),
        "innings": round(innings, 1)
    }

def get_batter_vs_pitcher(batter_id: int, pitcher_id: int) -> dict | None:
    url = (f"https://statsapi.mlb.com/api/v1/people/{batter_id}/stats"
           f"?stats=statSplits&group=hitting&opposingPlayerId={pitcher_id}")
    data = _get_json(url)
    if not data or "stats" not in data:
        return None
    stats = data["stats"]
    if not stats:
        return None
    splits = stats[0].get("splits", [])
    if not splits:
        return None
    main = splits[0].get("stat", {})
    return {
        "avg": main.get("avg"),
        "hits": main.get("hits", 0),
        "atBats": main.get("atBats", 0),
        "homeRuns": main.get("homeRuns", 0),
        "strikeOuts": main.get("strikeOuts", 0)
    }

def get_team_streak(team_id: int) -> str:
    current_year = datetime.now().year
    url = (f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
           f"?stats=gameLog&season={current_year}&group=hitting&gameType=R")
    data = _get_json(url)
    if not data or "stats" not in data:
        return ""
    stats = data["stats"]
    if not stats:
        return ""
    splits = stats[0].get("splits", [])
    if not splits:
        return ""
    streak = ""
    for game in splits[:10]:
        result = game.get("stat", {}).get("wins", 0)
        if result == 1:
            streak += "W"
        else:
            streak += "L"
    if not streak:
        return ""
    consecutive = streak[0]
    for ch in streak[1:]:
        if ch == consecutive[0]:
            consecutive += ch
        else:
            break
    return f"{consecutive[0]}{len(consecutive)}"

def get_team_id_by_name(team_name: str) -> int | None:
    """Busca el team ID de MLB a partir del nombre completo del equipo."""
    url = "https://statsapi.mlb.com/api/v1/teams?sportIds=1&season=" + str(datetime.now().year)
    data = _get_json(url)
    if not data or "teams" not in data:
        return None
    for team in data["teams"]:
        if team.get("name") and team["name"].lower() == team_name.lower():
            return team["id"]
    return None

def get_top_batters(team_name: str, limit: int = 3) -> list[dict]:
    """
    Obtiene los 'limit' primeros bateadores del lineup probable de un equipo.
    Esto es una aproximación usando el roster activo y ordenando por
    posición de bateo promedio (no es perfecto, pero útil).
    """
    team_id = get_team_id_by_name(team_name)
    if not team_id:
        return []
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster?season={datetime.now().year}"
    data = _get_json(url)
    if not data or "roster" not in data:
        return []
    batters = []
    for player in data["roster"]:
        if player.get("position", {}).get("abbreviation") == "P":
            continue  # excluir pitchers
        batters.append({
            "id": player["person"]["id"],
            "name": player["person"]["fullName"]
        })
    # Como la alineación real no está disponible, tomamos los primeros 'limit'
    return batters[:limit]

def get_probable_pitchers(event_id: str) -> list:
    url = f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event={event_id}"
    data = _get_json(url)
    if not data:
        return []
    pitchers = []
    header = data.get("header", {})
    competitions = header.get("competitions", [])
    if not competitions:
        competitions = data.get("competitions", [])
    if not competitions:
        return []
    comp = competitions[0]
    for competitor in comp.get("competitors", []):
        prob = competitor.get("probablePitcher")
        if prob:
            pitchers.append({
                "name": prob.get("displayName"),
                "id": prob.get("id"),
                "team": competitor.get("team", {}).get("displayName")
            })
    return pitchers