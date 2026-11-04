"""Mark XV - the Second Mind: persistent conversation intelligence.

Every turn of every session is logged locally (SQLite in the user config
directory - data never leaves the machine). Sessions get auto-titles from
their first user message, are searchable across all history, and can be
resumed into the live agent context.

Deliberate design:
- Pure stdlib sqlite3, zero dependencies.
- Logging happens AFTER a turn completes - a crashed or interrupted turn
  never leaves a half-written record.
- Search is literal-substring (LIKE with escaped wildcards, parameterized),
  which holds comfortably at personal-history scale.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS sessions ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " title TEXT NOT NULL,"
    " started_at TEXT NOT NULL"
    ");"
    "CREATE TABLE IF NOT EXISTS messages ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " session_id INTEGER NOT NULL REFERENCES sessions(id),"
    " role TEXT NOT NULL,"
    " content TEXT NOT NULL,"
    " created_at TEXT NOT NULL"
    ");"
)


def _db_path():
    # resolved through the config module so tests can redirect the directory
    return config.config_dir() / "conversations.db"


def _connect() -> sqlite3.Connection:
    _db_path().parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(_db_path()))
    connection.executescript(SCHEMA)
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start_session(title: str) -> int:
    connection = _connect()
    try:
        cursor = connection.execute(
            "INSERT INTO sessions (title, started_at) VALUES (?, ?)",
            (title.strip() or "Untitled session", _now()),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def log_message(session_id: int, role: str, content: str) -> None:
    connection = _connect()
    try:
        connection.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (int(session_id), role, content, _now()),
        )
        connection.commit()
    finally:
        connection.close()


def rename_session(session_id: int, title: str) -> None:
    connection = _connect()
    try:
        connection.execute(
            "UPDATE sessions SET title = ? WHERE id = ?", (title.strip(), int(session_id))
        )
        connection.commit()
    finally:
        connection.close()


def list_sessions(limit: int = 10) -> list[dict]:
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT s.id, s.title, s.started_at, COUNT(m.id) AS turns "
            "FROM sessions s LEFT JOIN messages m ON m.session_id = s.id "
            "GROUP BY s.id ORDER BY s.id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    finally:
        connection.close()
    return [
        {"id": r[0], "title": r[1], "started_at": r[2], "turns": r[3]} for r in rows
    ]


def search_history(query: str, limit: int = 10) -> list[dict]:
    # Escape LIKE wildcards so user input can only ever match literally,
    # then pass the pattern as a bound parameter - never string-concatenated.
    escaped = (
        query.strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT m.session_id, s.title, m.role, m.content, m.created_at "
            "FROM messages m JOIN sessions s ON s.id = m.session_id "
            "WHERE m.content LIKE ? ESCAPE '\\' ORDER BY m.id DESC LIMIT ?",
            (f"%{escaped}%", int(limit)),
        ).fetchall()
    finally:
        connection.close()
    return [
        {"session_id": r[0], "title": r[1], "role": r[2], "content": r[3], "created_at": r[4]}
        for r in rows
    ]


def session_messages(session_id: int) -> list[dict]:
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id",
            (int(session_id),),
        ).fetchall()
    finally:
        connection.close()
    return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]


def register_conversation_tools(registry) -> None:
    """Attach the Second Mind tools to a ToolRegistry."""

    def history_search(query: str, limit: int = 10) -> str:
        if not query.strip():
            return "ERROR: empty query"
        results = search_history(query, limit)
        if not results:
            return "No matching conversation history."
        return "\n---\n".join(
            f"[{r['created_at']}] {r['role']} ({r['title']}): {r['content'][:300]}"
            for r in results
        )

    def history_sessions(limit: int = 10) -> str:
        sessions = list_sessions(limit)
        if not sessions:
            return "No sessions recorded yet."
        return "\n".join(
            f"#{s['id']} [{s['started_at']}] {s['title']} ({s['turns']} turns)"
            for s in sessions
        )

    registry.register(
        "history_search",
        "Search ALL past conversation history (every session ever logged, "
        "locally). Use when prior conversations would change your answer.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
        history_search,
    )
    registry.register(
        "history_sessions",
        "List recent conversation sessions with ids and titles.",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        },
        history_sessions,
    )
