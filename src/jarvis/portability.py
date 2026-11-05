"""Mark XIX - export/import of a profile's brain, memories, conversations.

Schema versioning: EXPORT_SCHEMA = 1. The exporter refuses nothing; the
importer refuses unknown schema versions instead of guessing.

Secrets: API keys are EXCLUDED by default. include_secrets=True puts them in
the file - the CLI layer must obtain explicit confirmation before calling it
that way. License keys are never exported at all (reactivate per install).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from . import config

EXPORT_SCHEMA = 1


def export_profile(include_secrets: bool = False) -> dict:
    """Snapshot the ACTIVE profile as a versioned dict (caller writes the file)."""
    from .conversations import list_sessions, session_messages
    from .memory import recent_notes

    cfg = config.Config.load() or config.Config()
    config_dict = asdict(cfg)
    for brain in config_dict.get("brains", {}).values():
        if brain and not include_secrets:
            brain["api_key"] = ""

    sessions = list_sessions(10_000)
    messages: dict[int, list[dict]] = {}
    for session in sessions:
        messages[session["id"]] = [
            {"role": m["role"], "content": m["content"]}
            for m in session_messages(session["id"])
        ]

    return {
        "schema": EXPORT_SCHEMA,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "app_version": _version(),
        "profile": config.active_profile(),
        "secrets_included": bool(include_secrets),
        "config": config_dict,
        "memories": [
            {"content": note["content"], "created_at": note["created_at"]}
            for note in recent_notes(10_000)
        ],
        "conversations": {"sessions": sessions, "messages": messages},
    }


def validate_export(data: dict) -> None:
    """Raise ValueError unless data is an export this version understands."""
    if not isinstance(data, dict):
        raise ValueError("export file is not a JSON object")
    if data.get("schema") != EXPORT_SCHEMA:
        raise ValueError(
            f"unsupported export schema {data.get('schema')!r} "
            f"(this build understands schema {EXPORT_SCHEMA})"
        )
    for key in ("config", "memories", "conversations"):
        if key not in data:
            raise ValueError(f"export file is missing the {key!r} section")


def import_profile(data: dict) -> str:
    """Merge an export into the ACTIVE profile. Config is replaced by the
    file's config; memories and conversations are ADDED (merge, never
    destroy). Returns a human summary."""
    validate_export(data)
    from .conversations import log_message, rename_session, start_session
    from .memory import save_note

    from .config import Config

    # config: rebuild from the exported dict through the standard loader path
    raw = dict(data["config"])
    raw["version"] = max(1, int(raw.get("version", 4)))
    restored = Config._from_modern(raw) if int(raw["version"]) >= 2 else Config._from_v1(raw)
    restored.save()

    memories_added = 0
    for note in data.get("memories", []):
        content = str(note.get("content", "")).strip()
        if content:
            save_note(content)
            memories_added += 1

    sessions_added = 0
    messages_added = 0
    for session in data.get("conversations", {}).get("sessions", []):
        sid = start_session(str(session.get("title") or "Imported session"))
        sessions_added += 1
        for message in data.get("conversations", {}).get("messages", {}).get(
            str(session.get("id")), []
        ):
            role = message.get("role")
            if role in ("user", "assistant"):
                log_message(sid, role, str(message.get("content", "")))
                messages_added += 1

    secrets_note = "secrets included" if data.get("secrets_included") else "no secrets included"
    return (
        f"Imported into profile '{config.active_profile()}': config applied "
        f"({restored.brains.primary.provider} / {restored.brains.primary.model}), "
        f"{memories_added} memories added, {sessions_added} sessions / "
        f"{messages_added} messages added ({secrets_note})."
    )


def _version() -> str:
    from . import __version__

    return __version__
