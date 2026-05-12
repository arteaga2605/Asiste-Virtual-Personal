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

init_db()

# ---------- NOTAS ----------
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

# ---------- TAREAS ----------
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

def get_upcoming_tasks(hours: int = 24) -> list:
    """Devuelve las tareas pendientes cuyo deadline está dentro de las próximas 'hours' horas."""
    now = datetime.now()
    future = now + timedelta(hours=hours)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    future_str = future.strftime("%Y-%m-%d %H:%M")
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status = 'pending' AND deadline BETWEEN ? AND ? ORDER BY deadline",
        (now_str, future_str)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ---------- CONTACTOS ----------
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

# ---------- METAS ----------
def add_goal(description: str, target_value: float = 100, unit: str = "%") -> dict:
    conn = get_connection()
    conn.execute(
        "INSERT INTO goals (description, target_value, unit) VALUES (?, ?, ?)",
        (description, target_value, unit)
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "action": "add_goal"}

def list_goals(active_only: bool = True) -> list:
    conn = get_connection()
    if active_only:
        rows = conn.execute("SELECT * FROM goals WHERE active = 1 ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM goals ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_goal_progress(goal_id: int, current_value: float) -> dict:
    conn = get_connection()
    conn.execute("UPDATE goals SET current_value = ? WHERE id = ?", (current_value, goal_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

def deactivate_goal(goal_id: int) -> dict:
    conn = get_connection()
    conn.execute("UPDATE goals SET active = 0 WHERE id = ?", (goal_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

# ---------- INFORME SEMANAL ----------
def generate_weekly_report() -> str:
    now = datetime.now()
    since = now - timedelta(days=7)
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    tasks_done = conn.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'done' AND created_at >= ?",
        (since_str,)
    ).fetchone()["cnt"]

    new_notes = conn.execute(
        "SELECT COUNT(*) as cnt FROM notes WHERE created_at >= ?",
        (since_str,)
    ).fetchone()["cnt"]

    goals = conn.execute("SELECT * FROM goals WHERE active = 1").fetchall()

    try:
        interactions = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_history WHERE timestamp >= ?",
            (since_str,)
        ).fetchone()["cnt"]
    except:
        interactions = 0

    from tools.predictions import get_all_predictions
    predictions = get_all_predictions()
    total_preds = len(predictions)
    aciertos = 0
    for pred in predictions:
        event_id = pred["event_id"]
        from tools.sports import get_event_result
        result = get_event_result(pred["sport"], pred["league_slug"], event_id)
        if result and result.get("winner"):
            if pred["favorite"].lower() == result["winner"].lower():
                aciertos += 1

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
    if total_preds > 0:
        lines.append(f"  Predicciones deportivas totales: {total_preds} (aciertos: {aciertos})")
    else:
        lines.append("  Aún no hay predicciones deportivas registradas.")

    return "\n".join(lines)