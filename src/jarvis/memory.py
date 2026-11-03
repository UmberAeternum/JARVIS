"""Persistent local memory - a searchable second brain in SQLite.

Zero dependencies: stdlib sqlite3. The database lives in the user's config
directory (%APPDATA%\\jarvis\\memory.db on Windows) and never leaves the
machine. Search escapes SQL wildcards and uses a fully parameterized LIKE
with ESCAPE, so user input can never alter the query structure.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .config import config_dir

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS memories ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " content TEXT NOT NULL,"
    " created_at TEXT NOT NULL"
    ")"
)


def _db_path():
    return config_dir() / "memory.db"


def _connect() -> sqlite3.Connection:
    _db_path().parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(_db_path()))
    connection.executescript(_SCHEMA)
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_note(content: str) -> int:
    connection = _connect()
    try:
        cursor = connection.execute(
            "INSERT INTO memories (content, created_at) VALUES (?, ?)",
            (content.strip(), _now()),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def search_notes(query: str, limit: int = 5) -> list[dict]:
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
            "SELECT id, content, created_at FROM memories "
            "WHERE content LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT ?",
            (f"%{escaped}%", int(limit)),
        ).fetchall()
    finally:
        connection.close()
    return [{"id": r[0], "content": r[1], "created_at": r[2]} for r in rows]


def recent_notes(limit: int = 5) -> list[dict]:
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT id, content, created_at FROM memories ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    finally:
        connection.close()
    return [{"id": r[0], "content": r[1], "created_at": r[2]} for r in rows]


def forget_note(note_id: int) -> bool:
    connection = _connect()
    try:
        cursor = connection.execute("DELETE FROM memories WHERE id = ?", (int(note_id),))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def register_memory_tools(registry) -> None:
    """Attach the memory tools to a ToolRegistry."""

    def memory_save(note: str) -> str:
        if not note.strip():
            return "ERROR: empty note"
        note_id = save_note(note)
        return f"Saved memory #{note_id}."

    def memory_search(query: str, limit: int = 5) -> str:
        if not query.strip():
            return "ERROR: empty query"
        results = search_notes(query, limit)
        if not results:
            return "No matching memories."
        lines = [f"#{r['id']} [{r['created_at']}] {r['content']}" for r in results]
        return "\n".join(lines)

    def memory_recent(limit: int = 5) -> str:
        results = recent_notes(limit)
        if not results:
            return "Memory is empty."
        return "\n".join(f"#{r['id']} [{r['created_at']}] {r['content']}" for r in results)

    def memory_forget(memory_id: int) -> str:
        approved = registry.confirm(f"Permanently delete memory #{memory_id}?")
        if not approved:
            return "BLOCKED: the user declined."
        return f"Deleted memory #{memory_id}." if forget_note(memory_id) else (
            f"No memory with id {memory_id}."
        )

    registry.register(
        "memory_save",
        "Save a durable fact or preference about the user to persistent local "
        "memory. Use proactively for things worth remembering across sessions.",
        {
            "type": "object",
            "properties": {"note": {"type": "string", "description": "The fact to remember."}},
            "required": ["note"],
        },
        memory_save,
    )
    registry.register(
        "memory_search",
        "Search persistent local memory for previously saved facts.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
        memory_search,
    )
    registry.register(
        "memory_recent",
        "List the most recent persistent memories.",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
        },
        memory_recent,
    )
    registry.register(
        "memory_forget",
        "Permanently delete one memory by id (requires user confirmation).",
        {
            "type": "object",
            "properties": {"memory_id": {"type": "integer"}},
            "required": ["memory_id"],
        },
        memory_forget,
    )
