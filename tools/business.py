# tools/business.py
import sqlite3
from datetime import datetime
from config import BUSINESS_DB_PATH

def get_connection():
    conn = sqlite3.connect(BUSINESS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Crea las tablas si no existen."""
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
    """)
    conn.commit()
    conn.close()

# ------------------- NOTAS -------------------
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

# ------------------- TAREAS -------------------
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

# ------------------- CONTACTOS -------------------
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

# Inicializar la BD al importar
init_db()