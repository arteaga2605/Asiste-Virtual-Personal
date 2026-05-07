# tools/predictions.py
import sqlite3
import json
from datetime import datetime
from config import BUSINESS_DB_PATH

def init_predictions():
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            sport TEXT,
            league TEXT,
            league_slug TEXT,
            teams TEXT,
            favorite TEXT,
            response_json TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_predictions(predictions_data: list, response_json: str, events_meta: dict):
    """
    Guarda las predicciones en la base de datos.
    Si ya existe una predicción para el mismo event_id, la reemplaza.
    """
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    for pred in predictions_data:
        game_name = pred.get("game", "")
        favorite = pred.get("favorite", "")
        # Buscar event_id en events_meta comparando resúmenes
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
            # Eliminar cualquier predicción anterior con el mismo event_id para evitar duplicados
            conn.execute("DELETE FROM predictions WHERE event_id = ?", (event_id,))
            conn.execute(
                "INSERT INTO predictions (event_id, sport, league, league_slug, teams, favorite, response_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event_id, sport, league, league_slug, teams_json, favorite, response_json)
            )
    conn.commit()
    conn.close()

def get_all_predictions():
    """Obtiene todas las predicciones guardadas (sin duplicados)."""
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    rows = conn.execute("SELECT id, event_id, sport, league, league_slug, teams, favorite, timestamp FROM predictions").fetchall()
    conn.close()
    return [{"id": r[0], "event_id": r[1], "sport": r[2], "league": r[3], "league_slug": r[4], "teams": r[5], "favorite": r[6], "timestamp": r[7]} for r in rows]

# Inicializar al importar
init_predictions()