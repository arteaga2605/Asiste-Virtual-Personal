# tools/business.py
import sqlite3
from datetime import datetime, timedelta
from config import BUSINESS_DB_PATH

def get_connection():
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium',
            deadline TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            company TEXT,
            role TEXT,
            email TEXT,
            phone TEXT,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            target_value REAL,
            current_value REAL DEFAULT 0,
            unit TEXT DEFAULT '%',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()

# Inicializar al importar
init_db()

# ---------- NOTAS (ya existentes) ----------
def add_note(title: str, content: str) -> dict:
    conn = get_connection()
    conn.execute("INSERT INTO notes (title, content) VALUES (?, ?)", (title, content))
    conn.commit()
    conn.close()
    return {"status": "ok", "action": "add_note"}

def list_notes() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM notes ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ---------- TAREAS (ya existentes) ----------
def add_task(title: str, description: str = "", priority: str = "medium", deadline: str = "") -> dict:
    conn = get_connection()
    conn.execute("INSERT INTO tasks (title, description, priority, deadline) VALUES (?, ?, ?, ?)",
                 (title, description, priority, deadline))
    conn.commit()
    conn.close()
    return {"status": "ok", "action": "add_task"}

def list_tasks(status: str = "pending") -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM tasks WHERE status = ? ORDER BY deadline", (status,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_task_status(task_id: int, new_status: str) -> dict:
    conn = get_connection()
    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (new_status, task_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

# ---------- CONTACTOS (ya existentes) ----------
def add_contact(name: str, company: str = "", role: str = "", email: str = "", phone: str = "", notes: str = "") -> dict:
    conn = get_connection()
    conn.execute("INSERT INTO contacts (name, company, role, email, phone, notes) VALUES (?, ?, ?, ?, ?, ?)",
                 (name, company, role, email, phone, notes))
    conn.commit()
    conn.close()
    return {"status": "ok", "action": "add_contact"}

def list_contacts() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM contacts").fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ---------- NUEVAS FUNCIONES DE METAS ----------
def add_goal(description: str, target_value: float = 100, unit: str = "%") -> dict:
    """Añade una nueva meta al sistema."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO goals (description, target_value, unit) VALUES (?, ?, ?)",
        (description, target_value, unit)
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "action": "add_goal"}

def list_goals(active_only: bool = True) -> list:
    """Lista las metas. Si active_only es True, solo muestra las activas (active=1)."""
    conn = get_connection()
    if active_only:
        rows = conn.execute("SELECT * FROM goals WHERE active = 1 ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM goals ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_goal_progress(goal_id: int, current_value: float) -> dict:
    """Actualiza el valor actual de una meta."""
    conn = get_connection()
    conn.execute("UPDATE goals SET current_value = ? WHERE id = ?", (current_value, goal_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

def deactivate_goal(goal_id: int) -> dict:
    """Marca una meta como inactiva."""
    conn = get_connection()
    conn.execute("UPDATE goals SET active = 0 WHERE id = ?", (goal_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

# ---------- GENERACIÓN DE INFORMES SEMANALES ----------
def generate_weekly_report() -> str:
    """
    Genera un resumen de los últimos 7 días:
    - Tareas completadas
    - Nuevas notas
    - Metas actuales y progreso
    - Rendimiento del asistente (número de predicciones y aciertos deportivas)
    """
    now = datetime.now()
    since = now - timedelta(days=7)
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    # Tareas completadas (status = 'done')
    tasks_done = conn.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'done' AND created_at >= ?",
        (since_str,)
    ).fetchone()["cnt"]

    # Nuevas notas
    new_notes = conn.execute(
        "SELECT COUNT(*) as cnt FROM notes WHERE created_at >= ?",
        (since_str,)
    ).fetchone()["cnt"]

    # Metas activas
    goals = conn.execute("SELECT * FROM goals WHERE active = 1").fetchall()

    # Interacciones con el asistente (desde la tabla conversation_history, si existe)
    # Puede que no exista si nunca se ha creado, pero memory.py la crea.
    try:
        interactions = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_history WHERE timestamp >= ?",
            (since_str,)
        ).fetchone()["cnt"]
    except:
        interactions = 0

    # Predicciones deportivas (aciertos/fallos) recientes
    from tools.predictions import get_all_predictions
    predictions = get_all_predictions()
    recent_preds = [p for p in predictions if p["timestamp"] >= since_str]
    total_preds = len(recent_preds)
    aciertos = 0
    for pred in predictions:  # para rendimiento global, no solo esta semana
        event_id = pred["event_id"]
        from tools.sports import get_event_result
        result = get_event_result(pred["sport"], pred["league_slug"], event_id)
        if result and result.get("winner"):
            if pred["favorite"].lower() == result["winner"].lower():
                aciertos += 1
    total_preds_all = len(predictions)

    conn.close()

    lines = [
        "📄 **Informe Semanal** (últimos 7 días)\n",
        f"✅ Tareas completadas: {tasks_done}",
        f"📝 Nuevas notas: {new_notes}",
        "\n🎯 **Metas activas**:"
    ]
    if goals:
        for goal in goals:
            prog = f"{goal['current_value']}/{goal['target_value']} {goal['unit']}"
            lines.append(f"  - {goal['description']}: {prog}")
    else:
        lines.append("  Ninguna meta registrada.")

    lines.append("\n📊 **Rendimiento del asistente**:")
    lines.append(f"  Conversaciones esta semana: {interactions} interacciones")
    if total_preds_all > 0:
        lines.append(f"  Predicciones deportivas totales: {total_preds_all} (aciertos: {aciertos})")
    else:
        lines.append("  Aún no hay predicciones deportivas registradas.")

    return "\n".join(lines)