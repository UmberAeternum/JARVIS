"""Mark XVIII - diagnostics + opt-in crash reporting.

`jarvis diagnostics bundle` writes a zip with redacted support material:
version/OS/Python, license TIER (never the key), a redacted settings dump,
the tail of logs/app.log, and conversation METADATA (ids/titles/turns).
Message bodies are excluded unless --include-conversations is passed, and
even then every line goes through the redactor. license.key material never
enters the bundle.

Crash reporting is strictly opt-in (config diagnostics.crash_reports, default
False): on an unhandled exception a redacted crash file is written locally
and its path printed. Nothing is uploaded - ever.
"""

from __future__ import annotations

import platform
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .config import mask_key

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # UMBRA- license keys (payload.signature form)
    (re.compile(r"UMBRA-[A-Za-z0-9_.\-]{4,}"), "[REDACTED-LICENSE]"),
    # HTTP auth headers
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1[REDACTED]"),
    # common API key shapes (sk-..., ghp_..., AIza..., xoxb-...)
    (re.compile(r"\b(?:sk|ghp|gho|xoxb|xoxp)-[A-Za-z0-9_\-]{8,}"), "[REDACTED-KEY]"),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{8,}"), "[REDACTED-KEY]"),
    # email addresses
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[REDACTED-EMAIL]"),
)

LOG_MAX_CHARS = 200_000
LOG_TAIL_CHARS = 20_000


def redact_text(text: str) -> str:
    """Scrub credential shapes and emails from arbitrary text."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


# ------------------------------------------------------------------- log


def log_line(source: str, text: str) -> None:
    """Append one redacted line to logs/app.log. Never raises; capped size."""
    try:
        logs_dir = config.config_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        path = logs_dir / "app.log"
        existing = ""
        if path.exists():
            try:
                existing = path.read_text(encoding="utf-8")
            except OSError:
                existing = ""
        if len(existing) > LOG_MAX_CHARS:
            existing = existing[-LOG_MAX_CHARS:]
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"{stamp} [{source}] {redact_text(str(text))}\n"
        path.write_text(existing + line, encoding="utf-8")
    except OSError:
        pass  # logging must never break the caller


# ------------------------------------------------------------------ crash


def write_crash_report(exc: Exception) -> Path:
    """Write a redacted crash file into the config dir and log the event."""
    import traceback

    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = config.config_dir() / f"crash-{now}.txt"
    body = "\n".join([
        "UMBRA crash report (local only - nothing is uploaded)",
        f"when: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"version: {_version()}",
        f"platform: {platform.platform()}",
        f"python: {sys.version.split()[0]}",
        "",
        f"exception: {type(exc).__name__}: {redact_text(str(exc))}",
        "",
        redact_text(traceback.format_exc()[-50_000:]),
    ])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        if sys.platform != "win32":
            try:
                path.chmod(0o600)
            except OSError:
                pass
    except OSError:
        pass
    log_line("crash", f"{type(exc).__name__}: {exc}")
    return path


def maybe_report_crash(exc: Exception) -> int:
    """Opt-in crash hook for cli.main. With crash reporting disabled the
    previous behavior is preserved exactly (the exception re-raises)."""
    try:
        cfg = config.Config.load()
    except Exception:
        cfg = None
    if cfg is None or not cfg.diagnostics.crash_reports:
        raise exc
    path = write_crash_report(exc)
    print(f"UMBRA hit an unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"A crash report was written to: {path}", file=sys.stderr)
    print(
        "Run `jarvis diagnostics bundle` to collect a support bundle; "
        "include the crash file when contacting support.",
        file=sys.stderr,
    )
    return 1


# ----------------------------------------------------------------- bundle


def _version() -> str:
    from . import __version__

    return __version__


def _collect_info(cfg: config.Config) -> str:
    from . import licensing

    lines = [
        "UMBRA diagnostics",
        f"version: {_version()}",
        f"platform: {platform.platform()}",
        f"python: {sys.version.split()[0]}",
        f"tier: {licensing.tier()}  (license key itself is never included)",
        f"config file: {config.config_path()}",
        "",
        "store counts (metadata only - no content):",
    ]
    try:
        from .memory import recent_notes

        lines.append(f"  memories: {len(recent_notes(10_000))}")
    except Exception:
        lines.append("  memories: unavailable")
    try:
        from .conversations import list_sessions

        lines.append(f"  sessions: {len(list_sessions(10_000))}")
    except Exception:
        lines.append("  sessions: unavailable")
    try:
        from .sentinel import load_reminders

        lines.append(f"  reminders: {len(load_reminders())}")
    except Exception:
        lines.append("  reminders: unavailable")
    try:
        from .watchtower import load_rules

        lines.append(f"  watch rules: {len(load_rules())}")
    except Exception:
        lines.append("  watch rules: unavailable")
    key = cfg.brains.primary.api_key or ""
    lines.append(f"  primary api key: {mask_key(key)}")
    return "\n".join(lines)


def _conversations_meta() -> str:
    from .conversations import list_sessions

    lines = ["session id | title | turns | started_at  (message bodies are NOT included)"]
    for session in list_sessions(200):
        lines.append(
            f"  #{session['id']} | {session.get('title', '')} | "
            f"{session.get('turns', 0)} | {session.get('started_at', '')}"
        )
    return "\n".join(lines)


def _conversations_bodies() -> str:
    from .conversations import list_sessions, session_messages
    from .safety import truncate_output

    parts: list[str] = ["recent session transcripts (redacted):"]
    for session in list_sessions(5):
        parts.append(f"\n--- session #{session['id']} {session.get('title', '')} ---")
        for entry in session_messages(session["id"]):
            role = entry.get("role", "?")
            content = redact_text(str(entry.get("content", "")))
            parts.append(f"  [{role}] {content}")
    return truncate_output("\n".join(parts), limit=40_000)


def _log_tail() -> str:
    path = config.config_dir() / "logs" / "app.log"
    if not path.exists():
        return "(no app.log yet)"
    try:
        tail = path.read_text(encoding="utf-8")[-LOG_TAIL_CHARS:]
    except OSError:
        return "(app.log unreadable)"
    return redact_text(tail)


def build_bundle(
    cfg: config.Config,
    include_conversations: bool = False,
    out: Path | None = None,
) -> Path:
    """Write the redacted diagnostics zip; returns its path."""
    from .settings import show_text

    dest = out or (config.config_dir() / f"diagnostics-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip")
    dest.parent.mkdir(parents=True, exist_ok=True)
    members: dict[str, str] = {
        "info.txt": _collect_info(cfg),
        "config.txt": redact_text(show_text(cfg)),
        "app-log.txt": _log_tail(),
        "conversations-meta.txt": _conversations_meta(),
    }
    if include_conversations:
        members["conversations.txt"] = _conversations_bodies()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    log_line("diagnostics", f"bundle written: {dest.name} (conversations={include_conversations})")
    return dest
