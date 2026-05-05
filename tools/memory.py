# tools/memory.py
import sqlite3
from datetime import datetime
from config import BUSINESS_DB_PATH

def init_memory():
    """Crea la tabla de historial si no existe."""
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_message(role: str, content: str):
    """Guarda un mensaje en el historial."""
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    conn.execute(
        "INSERT INTO conversation_history (role, content) VALUES (?, ?)",
        (role, content)
    )
    conn.commit()
    conn.close()

def save_conversation(messages: list):
    """
    Guarda una lista completa de mensajes (cada uno es un dict con 'role' y 'content').
    Útil para persistir el historial después de una interacción completa.
    Normalmente guardaremos solo el mensaje del usuario y el del asistente,
    pero podemos guardar todo el historial (incluyendo mensajes del sistema/tool) si queremos.
    """
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    for msg in messages:
        # No guardar mensajes del sistema para no saturar
        if msg.get("role") in ("user", "assistant", "tool"):
            conn.execute(
                "INSERT INTO conversation_history (role, content) VALUES (?, ?)",
                (msg["role"], msg["content"])
            )
    conn.commit()
    conn.close()

def load_recent_history(limit: int = 20) -> list:
    """
    Carga los últimos 'limit' mensajes del historial (ordenados por timestamp).
    Retorna una lista de diccionarios con 'role' y 'content', lista para usar como historial.
    """
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    rows = conn.execute(
        "SELECT role, content FROM conversation_history ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    # Invertir para que quede en orden cronológico (más antiguo primero)
    messages = [{"role": row[0], "content": row[1]} for row in reversed(rows)]
    return messages

# Inicializar tabla al importar
init_memory()