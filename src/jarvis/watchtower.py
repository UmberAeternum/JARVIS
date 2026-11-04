"""Mark XI - the Watchtower: ambient awareness rules for the Sentinel.

The Sentinel announces what it is TOLD to (reminders). The Watchtower
announces what it NOTICES: threshold rules on system vitals, shifts in the
health screening, and changes in watched folders. Rules are stored locally
(watchtower.json), evaluated every Sentinel cycle, and announced through the
same TTS path - with per-rule cooldowns so a screaming CPU does not nag every
20 seconds.

Deliberate scope: read-only signals only. The Watchtower notices and
reports; it never acts. No API key, no cloud - everything is local.

Rule kinds:
- vitals: {signal: cpu|ram|disk_used|battery, op: >|<, value: N}
- folder: {path: dir} - fires when the folder's file count or newest
          modification time changes (new/updated/removed files)
- health: fires when the Oracle's screening band changes from the last
          announcement (e.g. BASELINE -> ELEVATED)
"""

from __future__ import annotations

import json
import os

from . import config

RULE_KINDS = ("vitals", "folder", "health")


def _watchtower_path():
    # resolved through the config module so tests can redirect the directory
    return config.config_dir() / "watchtower.json"


def load_rules() -> list[dict]:
    path = _watchtower_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (OSError, ValueError):
        pass
    return []


def save_rules(rules: list[dict]) -> None:
    path = _watchtower_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rules, indent=2), encoding="utf-8")


def add_rule(rule: dict) -> dict:
    rules = load_rules()
    next_id = max((r.get("id", 0) for r in rules), default=0) + 1
    rule = dict(rule, id=next_id)
    rules.append(rule)
    save_rules(rules)
    return rule


def remove_rule(rule_id: int) -> bool:
    rules = load_rules()
    kept = [r for r in rules if r.get("id") != int(rule_id)]
    if len(kept) == len(rules):
        return False
    save_rules(kept)
    return True


# ------------------------------------------------------------------ evaluate


def read_vitals() -> dict[str, float | None]:
    """Current readings. Returns {} entries as None when unavailable."""
    readings: dict[str, float | None] = {"cpu": None, "ram": None, "disk_used": None, "battery": None}
    try:
        import psutil

        readings["cpu"] = psutil.cpu_percent(interval=0.3)
        readings["ram"] = psutil.virtual_memory().percent
        disk = psutil.disk_usage(str(__import__("pathlib").Path.home()))
        readings["disk_used"] = disk.percent
        battery = psutil.sensors_battery()
        readings["battery"] = battery.percent if battery else None
    except Exception:
        pass
    return readings


def evaluate_vitals(rule: dict, readings: dict[str, float | None]) -> str | None:
    """Return an announcement when the rule crosses its threshold, else None."""
    signal = str(rule.get("signal", ""))
    if signal not in readings or readings[signal] is None:
        return None
    current = float(readings[signal])
    target = float(rule.get("value", 0))
    crosses = current > target if rule.get("op", ">") == ">" else current < target
    if not crosses:
        return None
    custom = str(rule.get("text", "")).strip()
    if custom:
        return custom
    return (
        f"{signal} is at {current:.0f} - the rule set {rule.get('op')} {target} "
        f"has triggered, Sir."
    )


def describe_folder_change(path: str, previous: tuple[int, float],
                           current: tuple[int, float]) -> str:
    count, newest = current
    return (
        f"Activity in {path}: {count} files, latest change at "
        f"{datetime_from_timestamp(newest)}."
    )


def datetime_from_timestamp(timestamp: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def folder_snapshot(path: str) -> tuple[int, float] | None:
    """(file count, newest modification time) for a directory, else None."""
    base = path
    if not os.path.isdir(base):
        return None
    count = 0
    newest = 0.0
    with os.scandir(base) as entries:
        for entry in entries:
            try:
                if entry.is_file():
                    count += 1
                    newest = max(newest, entry.stat().st_mtime)
            except OSError:
                continue
    return (count, newest)


def evaluate_health(rule: dict, last_band: str | None, current_band: str | None) -> str | None:
    """Fire when the Oracle's band shifts between announcements."""
    if current_band is None or current_band == last_band:
        return None
    if current_band == "BASELINE":
        return f"Health screening returned to {current_band}."
    return f"Health screening is now {current_band} - check the Oracle report."


def cooldown_passed(rule: dict, last_fired: dict, now_ts: float) -> bool:
    cooldown_min = max(1, int(rule.get("cooldown_min", 30)))
    last = last_fired.get(rule.get("id"))
    if last is None:
        return True
    return (now_ts - float(last)) >= cooldown_min * 60


def register_watchtower_tools(registry) -> None:
    """Attach the watch-rule tools to a ToolRegistry."""

    def watch_set(kind: str, signal: str = "", op: str = ">", value: float = 0.0,
                  path: str = "", text: str = "", cooldown_min: int = 30) -> str:
        if kind == "vitals":
            if signal not in ("cpu", "ram", "disk_used", "battery"):
                return "ERROR: signal must be cpu, ram, disk_used or battery"
            if op not in (">", "<"):
                return "ERROR: op must be > or <"
            rule = {"kind": kind, "signal": signal, "op": op, "value": float(value),
                    "text": text, "cooldown_min": int(cooldown_min)}
        elif kind == "folder":
            if not path.strip():
                return "ERROR: path is required for a folder watch"
            rule = {"kind": kind, "path": path.strip(), "cooldown_min": int(cooldown_min)}
        elif kind == "health":
            rule = {"kind": kind, "cooldown_min": int(cooldown_min)}
        else:
            return f"ERROR: kind must be one of {', '.join(RULE_KINDS)}"
        saved = add_rule(rule)
        return f"Watch rule #{saved['id']} set ({kind})."

    def watch_list() -> str:
        rules = load_rules()
        if not rules:
            return "No watch rules set."
        return "\n".join(f"#{r['id']} [{r['kind']}] " + json.dumps(
            {k: v for k, v in r.items() if k not in ("id", "kind")}) for r in rules)

    def watch_remove(rule_id: int) -> str:
        approved = registry.confirm(f"Remove watch rule #{rule_id}?")
        if not approved:
            return "BLOCKED: the user declined."
        return (
            f"Removed watch rule #{rule_id}."
            if remove_rule(rule_id)
            else f"No watch rule with id {rule_id}."
        )

    registry.register(
        "watch_set",
        "Set a Watchtower rule the Sentinel evaluates every cycle and announces "
        "when triggered. kinds: vitals (signal cpu/ram/disk_used/battery with op "
        "and value), folder (path), health (Oracle band shift).",
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(RULE_KINDS)},
                "signal": {"type": "string"},
                "op": {"type": "string"},
                "value": {"type": "number"},
                "path": {"type": "string"},
                "text": {"type": "string", "description": "Custom announcement text."},
                "cooldown_min": {"type": "integer", "minimum": 1},
            },
            "required": ["kind"],
        },
        watch_set,
    )
    registry.register(
        "watch_list",
        "List all Watchtower rules.",
        {"type": "object", "properties": {}},
        watch_list,
    )
    registry.register(
        "watch_remove",
        "Remove a Watchtower rule by id (requires user confirmation).",
        {
            "type": "object",
            "properties": {"rule_id": {"type": "integer"}},
            "required": ["rule_id"],
        },
        watch_remove,
    )
