"""Mark VIII - the Sentinel: the proactive layer.

The assistant so far has been purely reactive - it answers when asked. The
Sentinel initiates: persisted reminders (one-shot or daily), a spoken morning
briefing composed from local data (health screening, kanban digest, memory
recap), and a standalone daemon (`jarvis sentinel`) that announces them aloud
via offline TTS.

Deliberate scope: the Sentinel announces, it does not act. Reminders fire as
spoken text only - no tool execution happens while the user is away from the
confirmation gates. It also needs no API key: everything is local, so it
works even before the brain is configured.

Time rules:
- "HH:MM"              -> daily reminder at that wall-clock time
- ISO datetime or
  "YYYY-MM-DD HH:MM"   -> one-shot reminder at that moment (fires once due)
Due logic is pure (due_now takes `now`) so it is fully testable.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

from . import config, health, watchtower

KIND_DAILY = "daily"
KIND_ONCE = "once"

_TIME_ONLY = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _reminders_path():
    # resolved through the config module so tests can redirect the directory
    return config.config_dir() / "sentinel.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _utc_now().isoformat(timespec="seconds")


def parse_when(raw: str) -> tuple[str, str]:
    """Parse user-supplied time into (kind, normalized_value).

    "07:30"                    -> ("daily", "07:30")
    "2026-11-10 07:30"         -> ("once", ISO with offset)
    "2026-11-10T07:30:00+02:00"-> ("once", ISO, offset preserved)
    Raises ValueError with a readable message otherwise.
    """
    raw = (raw or "").strip()
    if _TIME_ONLY.match(raw):
        return KIND_DAILY, raw
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, pattern)
            return KIND_ONCE, parsed.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return KIND_ONCE, parsed.isoformat(timespec="seconds")
    except ValueError:
        pass
    raise ValueError(
        "could not parse time - use HH:MM for a daily reminder, or "
        "'YYYY-MM-DD HH:MM' for a one-shot reminder"
    )


def load_reminders() -> list[dict]:
    path = _reminders_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (OSError, ValueError):
        pass
    return []


def save_reminders(reminders: list[dict]) -> None:
    path = _reminders_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reminders, indent=2), encoding="utf-8")


def add_reminder(text: str, when_raw: str) -> dict:
    kind, value = parse_when(when_raw)
    reminders = load_reminders()
    next_id = max((r.get("id", 0) for r in reminders), default=0) + 1
    reminder = {
        "id": next_id,
        "text": text.strip(),
        "kind": kind,
        "when": value,
        "created_at": _now_iso(),
    }
    reminders.append(reminder)
    save_reminders(reminders)
    return reminder


def cancel_reminder(reminder_id: int) -> bool:
    reminders = load_reminders()
    kept = [r for r in reminders if r.get("id") != int(reminder_id)]
    if len(kept) == len(reminders):
        return False
    save_reminders(kept)
    return True


def due_now(reminder: dict, now: datetime, fired_on: dict[int, str]) -> bool:
    """Pure due-check: has this reminder become due at `now`?

    daily: fires the first time `now` has passed its wall-clock time on a day
           it has not already fired (tracked by fired_on[id] = 'YYYY-MM-DD').
    once:  fires the first time `now` is past its stored moment.
    """
    if reminder.get("kind") == KIND_DAILY:
        try:
            hour, minute = (int(part) for part in str(reminder.get("when", "")).split(":"))
        except ValueError:
            return False
        today = now.strftime("%Y-%m-%d")
        if fired_on.get(reminder.get("id")) == today:
            return False
        return (now.hour, now.minute) >= (hour, minute)
    try:
        when = datetime.fromisoformat(str(reminder.get("when", "")))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return now >= when


def compose_briefing() -> str:
    """Morning briefing from local data: health, kanban, memory. Honest
    about missing pieces; needs no API key and no brain."""
    from . import health
    from .memory import recent_notes
    from .portal import load_board

    lines = ["Good morning, Sir. The briefing:"]

    report = health.risk_assessment()
    lines.append("Health: " + report.splitlines()[0])

    board = load_board()
    tasks = board.get("tasks", [])
    todo = [t for t in tasks if t.get("column") == "todo"]
    doing = [t for t in tasks if t.get("column") == "doing"]
    lines.append(f"Kanban: {len(doing)} in progress, {len(todo)} waiting.")

    memories = recent_notes(3)
    if memories:
        lines.append("Recent memory: " + memories[0]["content"][:120])

    lines.append(health.DISCLAIMER)
    return "\n".join(lines)


def register_sentinel_tools(registry) -> None:
    """Attach reminder tools to a ToolRegistry."""

    def reminder_set(text: str, at_time: str) -> str:
        if not text.strip():
            return "ERROR: empty reminder text"
        try:
            kind, value = parse_when(at_time)
        except ValueError as exc:
            return f"ERROR: {exc}"
        reminder = add_reminder(text, at_time)
        when_text = f"daily at {value}" if kind == KIND_DAILY else f"at {value}"
        return f"Reminder #{reminder['id']} set {when_text}: {reminder['text']}"

    def reminder_list() -> str:
        reminders = load_reminders()
        if not reminders:
            return "No reminders set."
        return "\n".join(
            f"#{r['id']} [{r['kind']}] {r['when']}: {r['text']}" for r in reminders
        )

    def reminder_cancel(reminder_id: int) -> str:
        approved = registry.confirm(f"Cancel reminder #{reminder_id}?")
        if not approved:
            return "BLOCKED: the user declined."
        return (
            f"Cancelled reminder #{reminder_id}."
            if cancel_reminder(reminder_id)
            else f"No reminder with id {reminder_id}."
        )

    registry.register(
        "reminder_set",
        "Set a reminder the Sentinel daemon will announce aloud. at_time is "
        "'HH:MM' for a daily reminder or 'YYYY-MM-DD HH:MM' for one-shot.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to announce."},
                "at_time": {"type": "string", "description": "HH:MM (daily) or a date-time (one-shot)."},
            },
            "required": ["text", "at_time"],
        },
        reminder_set,
    )
    registry.register(
        "reminder_list",
        "List all active Sentinel reminders.",
        {"type": "object", "properties": {}},
        reminder_list,
    )
    registry.register(
        "reminder_cancel",
        "Cancel a reminder by id (requires user confirmation).",
        {
            "type": "object",
            "properties": {"reminder_id": {"type": "integer"}},
            "required": ["reminder_id"],
        },
        reminder_cancel,
    )


def run_sentinel(console, interval_s: int = 20, briefing_time: str = "08:00") -> int:
    """The standalone daemon: fires due reminders and the daily briefing,
    printed and spoken. Announces only - no tool execution happens unattended."""
    try:
        briefing_kind, briefing_value = parse_when(briefing_time)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    if briefing_kind != KIND_DAILY:
        console.print("[red]briefing_time must be HH:MM (daily)[/]")
        return 1

    reminders = load_reminders()
    fired_on: dict[object, str] = {}
    watch_last_fired: dict[object, float] = {}
    watch_last_band: dict[str, str | None] = {"band": None}
    folder_snaps: dict[str, tuple[int, float]] = {}
    tts = None
    try:
        import pyttsx3

        tts = pyttsx3.init()
    except Exception as exc:
        console.print(f"[yellow]TTS unavailable ({exc}) - announcements print only.[/]")

    def announce(text: str) -> None:
        console.print(f"[bold cyan]SENTINEL:[/] {text}")
        if tts is not None:
            try:
                tts.say(text)
                tts.runAndWait()
            except Exception:
                pass

    from rich.panel import Panel

    from . import watchtower

    console.print(
        Panel(
            f"Sentinel online - checking every {interval_s}s. "
            f"Reminders loaded: {len(reminders)}. Watch rules loaded: "
            f"{len(watchtower.load_rules())}. Briefing at {briefing_value}. "
            "Ctrl+C to stand down.",
            title="THE SENTINEL",
            border_style="cyan",
        )
    )
    try:
        while True:
            now = datetime.now().astimezone()  # local, tz-aware: wall-clock reminders
            for reminder in load_reminders():  # reloaded: /reminder_set may run elsewhere
                if due_now(reminder, now, fired_on):
                    announce(f"{reminder['text']} (reminder #{reminder['id']})")
                    if reminder.get("kind") == KIND_DAILY:
                        fired_on[reminder["id"]] = now.strftime("%Y-%m-%d")
                    else:
                        cancel_reminder(reminder["id"])  # one-shot: fired once
            if due_now(
                {"kind": KIND_DAILY, "when": briefing_value, "id": "briefing"},
                now,
                fired_on,
            ):
                fired_on["briefing"] = now.strftime("%Y-%m-%d")
                announce(compose_briefing())

            # Mark XI - the Watchtower: ambient rules, evaluated each cycle
            for rule in [r for r in watchtower.load_rules() if r.get("kind") == "vitals"]:
                if not watchtower.cooldown_passed(rule, watch_last_fired, time.time()):
                    continue
                finding = watchtower.evaluate_vitals(rule, watchtower.read_vitals())
                if finding:
                    watch_last_fired[rule["id"]] = time.time()
                    announce(finding)

            for rule in [r for r in watchtower.load_rules() if r.get("kind") == "folder"]:
                path = str(rule.get("path", ""))
                current = watchtower.folder_snapshot(path)
                if current is None:
                    continue
                previous = folder_snaps.get(path)
                folder_snaps[path] = current
                if previous is None or previous == current:
                    continue
                if watchtower.cooldown_passed(rule, watch_last_fired, time.time()):
                    watch_last_fired[rule["id"]] = time.time()
                    announce(watchtower.describe_folder_change(path, previous, current))

            for rule in [r for r in watchtower.load_rules() if r.get("kind") == "health"]:
                report = health.risk_assessment()
                first = report.splitlines()[0] if report else ""
                band = next(
                    (b for b in ("HIGH", "ELEVATED", "WATCH", "BASELINE") if b in first),
                    None,
                )
                finding = watchtower.evaluate_health(rule, watch_last_band.get("band"), band)
                watch_last_band["band"] = band
                if finding:
                    if watchtower.cooldown_passed(rule, watch_last_fired, time.time()):
                        watch_last_fired[rule["id"]] = time.time()
                        announce(finding)
            time.sleep(interval_s)
    except KeyboardInterrupt:
        console.print("[dim]Sentinel standing down, Sir.[/]")
    return 0
