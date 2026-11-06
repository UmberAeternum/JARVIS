"""Mark XXVIII - the personality pack: honorific, verbosity, humor, proactivity.

Stored as personality.json in the config directory. JSON instead of YAML is a
deliberate stdlib choice (no yaml dependency) - noted assumption for this
mark. Defaults are the Iron Man JARVIS register: dry, precise, "Sir".

Validation is strict: unknown verbosity, out-of-range humor/proactive, or a
non-string/overlong honorific raise ValueError with a readable message.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config

DEFAULTS: dict = {
    "honorific": "Sir",       # how UMBRA addresses the user
    "verbosity": "concise",   # concise | normal | chatty
    "humor": 5,               # 0 (stereo butler) .. 10 (Tony's workshop)
    "proactive": 1,           # 0 off .. 2 eager nudges
}

_VERBOSITIES = ("concise", "normal", "chatty")


def personality_path() -> Path:
    return config.config_dir() / "personality.json"


def _validate(values: dict) -> dict:
    honorific = values.get("honorific", DEFAULTS["honorific"])
    if not isinstance(honorific, str) or not (0 < len(honorific) <= 24):
        raise ValueError("honorific must be a string of 1-24 characters")
    verbosity = values.get("verbosity", DEFAULTS["verbosity"])
    if verbosity not in _VERBOSITIES:
        raise ValueError(f"verbosity must be one of {', '.join(_VERBOSITIES)}")
    for key, low, high in (("humor", 0, 10), ("proactive", 0, 2)):
        level = values.get(key, DEFAULTS[key])
        if not isinstance(level, int) or isinstance(level, bool) or not low <= level <= high:
            raise ValueError(f"{key} must be an integer {low}-{high}")
    return values


def load() -> dict:
    """Merged personality (defaults fill in), or defaults when absent/corrupt."""
    values = dict(DEFAULTS)
    path = personality_path()
    if not path.is_file():
        return values
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            known = {key: raw[key] for key in DEFAULTS if key in raw}
            values.update(known)
    except (OSError, ValueError):
        pass
    try:
        _validate(values)
    except ValueError:
        return dict(DEFAULTS)  # corrupt pack falls back to the register
    return values


def save(updates: dict) -> dict:
    """Validate + merge updates over the current pack, persist, return it."""
    current = load()
    merged = {**current, **updates}
    _validate(merged)
    path = personality_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged
