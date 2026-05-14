# tools/predictions.py
import sqlite3
import json
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
            predicted_score TEXT,
            confidence INTEGER DEFAULT 0,
            response_json TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        conn.execute("ALTER TABLE predictions ADD COLUMN predicted_score TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE predictions ADD COLUMN confidence INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS crypto_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
            direction TEXT NOT NULL,
            target_price REAL,
            current_price REAL,
            response_json TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            checked INTEGER DEFAULT 0,
            result TEXT,
            trello_card_id TEXT
        )
    """)
    # Añadir columna si no existe
    try:
        conn.execute("ALTER TABLE crypto_predictions ADD COLUMN trello_card_id TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

def save_predictions(predictions_data: list, response_json: str, events_meta: dict):
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    for pred in predictions_data:
        game_name = pred.get("game", "")
        favorite = pred.get("favorite", "")
        score = pred.get("score", "")
        confidence = pred.get("confidence", 0)
        try:
            conf_int = int(confidence)
        except:
            conf_int = 0
        if conf_int < 50:
            continue
        event_id = None
        sport = ""
        league = ""
        league_slug = ""
        teams_json = ""
        for eid, meta in events_meta.items():
            if meta.get("summary", "") == game_name:
                event_id = eid
                sport = meta.get("sport", "")
                league = meta.get("league", "")
                league_slug = meta.get("league_slug", "")
                teams_json = json.dumps(meta.get("teams", []))
                break
        if not event_id:
            for eid, meta in events_meta.items():
                summary = meta.get("summary", "")
                words_pred = set(game_name.lower().replace("-", " ").split())
                words_summary = set(summary.lower().split())
                if len(words_pred & words_summary) >= 2:
                    event_id = eid
                    sport = meta.get("sport", "")
                    league = meta.get("league", "")
                    league_slug = meta.get("league_slug", "")
                    teams_json = json.dumps(meta.get("teams", []))
                    break
        if event_id:
            conn.execute("DELETE FROM predictions WHERE event_id = ?", (event_id,))
            conn.execute(
                "INSERT INTO predictions (event_id, sport, league, league_slug, teams, favorite, predicted_score, confidence, response_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, sport, league, league_slug, teams_json, favorite, score, conf_int, response_json)
            )
    conn.commit()
    conn.close()

def get_all_predictions():
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    rows = conn.execute("SELECT id, event_id, sport, league, league_slug, teams, favorite, predicted_score, confidence, timestamp FROM predictions").fetchall()
    conn.close()
    return [{"id": r[0], "event_id": r[1], "sport": r[2], "league": r[3], "league_slug": r[4],
             "teams": r[5], "favorite": r[6], "predicted_score": r[7], "confidence": r[8], "timestamp": r[9]} for r in rows]

def save_crypto_prediction(symbol: str, direction: str, target_price: float, current_price: float, response_json: str) -> int:
    """Guarda una predicción de criptomoneda y devuelve su ID."""
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    cur = conn.execute(
        "INSERT INTO crypto_predictions (symbol, direction, target_price, current_price, response_json) VALUES (?, ?, ?, ?, ?)",
        (symbol, direction, target_price, current_price, response_json)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def update_crypto_prediction_trello(pred_id: int, trello_card_id: str):
    """Asigna el ID de tarjeta de Trello a una predicción."""
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    conn.execute("UPDATE crypto_predictions SET trello_card_id = ? WHERE id = ?", (trello_card_id, pred_id))
    conn.commit()
    conn.close()

def get_all_crypto_predictions():
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    rows = conn.execute("SELECT id, symbol, direction, target_price, current_price, response_json, timestamp, checked, result, trello_card_id FROM crypto_predictions").fetchall()
    conn.close()
    return [{"id": r[0], "symbol": r[1], "direction": r[2], "target_price": r[3],
             "current_price": r[4], "response_json": r[5], "timestamp": r[6],
             "checked": r[7], "result": r[8], "trello_card_id": r[9]} for r in rows]

def update_crypto_prediction_result(pred_id: int, result: str):
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    conn.execute("UPDATE crypto_predictions SET result = ?, checked = 1 WHERE id = ?", (result, pred_id))
    conn.commit()
    conn.close()

init_predictions()