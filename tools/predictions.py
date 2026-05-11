# tools/predictions.py
import sqlite3
import json
from config import BUSINESS_DB_PATH

def init_predictions():
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    # Crear la tabla si no existe (con todas las columnas actuales)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            sport TEXT,
            league TEXT,
            league_slug TEXT,
            teams TEXT,
            favorite TEXT,
            predicted_score TEXT,
            response_json TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Añadir la columna predicted_score si no existe (para bases de datos antiguas)
    try:
        conn.execute("ALTER TABLE predictions ADD COLUMN predicted_score TEXT")
    except sqlite3.OperationalError:
        # La columna ya existe, no se hace nada
        pass
    conn.commit()
    conn.close()

def save_predictions(predictions_data: list, response_json: str, events_meta: dict):
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    for pred in predictions_data:
        game_name = pred.get("game", "")
        favorite = pred.get("favorite", "")
        score = pred.get("score", "")
        event_id = None
        sport = ""
        league = ""
        league_slug = ""
        teams_json = ""
        for eid, meta in events_meta.items():
            if game_name in meta.get("summary", ""):
                event_id = eid
                sport = meta.get("sport", "")
                league = meta.get("league", "")
                league_slug = meta.get("league_slug", "")
                teams_json = json.dumps(meta.get("teams", []))
                break
        if event_id:
            conn.execute("DELETE FROM predictions WHERE event_id = ?", (event_id,))
            conn.execute(
                "INSERT INTO predictions (event_id, sport, league, league_slug, teams, favorite, predicted_score, response_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, sport, league, league_slug, teams_json, favorite, score, response_json)
            )
    conn.commit()
    conn.close()

def get_all_predictions():
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    rows = conn.execute("SELECT id, event_id, sport, league, league_slug, teams, favorite, predicted_score, timestamp FROM predictions").fetchall()
    conn.close()
    return [{"id": r[0], "event_id": r[1], "sport": r[2], "league": r[3], "league_slug": r[4],
             "teams": r[5], "favorite": r[6], "predicted_score": r[7], "timestamp": r[8]} for r in rows]

init_predictions()