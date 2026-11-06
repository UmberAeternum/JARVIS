"""Mark XXXI - the EDITH protocol: consent, ledger, revocation.

Default state = ZERO reach. Reach capabilities (self-install, API chat,
overlay attachment) are denied until the user interactively types the
confirmation phrase. The grant:

- lives in <config>/access-state.json with a device fingerprint and a hard
  expiry (default 24h, configurable window) - it must be re-granted after
  expiry, so it never persists indefinitely across restarts;
- can ONLY be created by `jarvis access grant --full` typed interactively -
  never by config files, env vars, CLI flags, API calls, or automation (the
  API exposes no grant endpoint; the CLI flag path requires the phrase too);
- is per-machine: the stored fingerprint must match the current machine.

Every cross-device / cross-app action is written to an append-only,
tamper-evident ledger (<config>/access-log.jsonl): each entry chains the
SHA-256 of the previous entry, so edits are detectable. `jarvis access log`
prints it; `jarvis access revoke --all` clears the grant instantly.

Honest threat model: the machine owner can always edit their own files - the
protocol's controls target automation, accidents, and persistence, not a
user attacking their own box. Hard prohibitions (no self-propagation, no
silent grants, no bypass) are test-enforced in the smoke suite.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from . import config

CONFIRMATION_PHRASE = "I grant UMBRA full access"
DEFAULT_WINDOW_H = 24


class AccessConfig:
    """Grant window only - the grant itself can never come from config."""

    window_hours: int = DEFAULT_WINDOW_H


def _state_path() -> Path:
    return config.config_dir() / "access-state.json"


def _log_path() -> Path:
    return config.config_dir() / "access-log.jsonl"


def device_fingerprint() -> str:
    """Stable per-machine fingerprint (hostname + platform + MAC hash)."""
    import platform
    import uuid

    raw = f"{platform.node()}|{platform.platform()}|{uuid.getnode():012x}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    if sys.platform != "win32":
        try:
            path.chmod(0o600)
        except OSError:
            pass


def full_active(now: float | None = None) -> bool:
    """True only when a grant exists, is unexpired, and matches this machine."""
    state = _load_state()
    if not state.get("full"):
        return False
    if state.get("fingerprint") != device_fingerprint():
        return False
    now = time.time() if now is None else now
    expires = float(state.get("expires_ts", 0))
    return now < expires


def window_hours() -> int:
    """Grant validity window. Config may shorten/lengthen validity but can
    never create a grant (see module docstring)."""
    try:
        cfg = config.Config.load()
        if cfg is not None:
            return max(1, int(getattr(cfg.access, "window_hours", DEFAULT_WINDOW_H)))
    except Exception:
        pass
    return DEFAULT_WINDOW_H


def grant_full(phrase_input: str) -> tuple[bool, str]:
    """Create the full-access grant. Returns (ok, message). The phrase must
    be typed by a human - callers pass whatever the user typed."""
    typed = (phrase_input or "").strip()
    if typed != CONFIRMATION_PHRASE:
        log_append("grant_denied", "confirmation phrase mismatch")
        return False, "confirmation phrase did not match - grant NOT created."
    state = {
        "full": True,
        "granted_ts": time.time(),
        "expires_ts": time.time() + window_hours() * 3600,
        "fingerprint": device_fingerprint(),
    }
    _save_state(state)
    log_append("grant_full", f"full access granted, expires in {window_hours()}h")
    return True, (
        f"FULL ACCESS granted - expires in {window_hours()}h. "
        "Every reach action is logged; revoke with jarvis access revoke --all."
    )


def revoke_all() -> str:
    _save_state({"full": False, "fingerprint": device_fingerprint()})
    log_append("revoke_all", "full access revoked")
    return "FULL ACCESS revoked - reach capabilities are denied again."


def require_full(action: str) -> bool:
    """The gate every reach capability calls first. Logs the attempt either
    way; returns whether the action may proceed."""
    if full_active():
        log_append("reach_allowed", action)
        return True
    log_append("reach_denied", action)
    return False


def status_text() -> str:
    state = _load_state()
    if not state.get("full"):
        return "FULL ACCESS: not granted"
    if state.get("fingerprint") != device_fingerprint():
        return "FULL ACCESS: not granted (grant belongs to another machine)"
    if time.time() >= float(state.get("expires_ts", 0)):
        return "FULL ACCESS: not granted (expired - re-grant with jarvis access grant --full)"
    since = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(state["granted_ts"])))
    expires = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(state["expires_ts"])))
    return f"FULL ACCESS: granted since {since}, expires {expires}"


# ------------------------------------------------------------------ ledger


def _entry_hash(prev_hash: str, entry: dict) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def log_append(action: str, detail: str) -> None:
    """Append one tamper-evident entry (chained hashes). Never raises."""
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        prev_hash = "0" * 64
        if path.is_file():
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if lines:
                try:
                    prev_hash = json.loads(lines[-1]).get("hash", prev_hash)
                except ValueError:
                    prev_hash = "0" * 64
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "action": action,
            "detail": detail,
        }
        entry["hash"] = _entry_hash(prev_hash, entry)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # the ledger must never break the caller


def log_entries() -> list[dict]:
    """All ledger entries, oldest first, with integrity verdicts."""
    path = _log_path()
    if not path.is_file():
        return []
    entries: list[dict] = []
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []
    prev = "0" * 64
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            entries.append({"ts": "?", "action": "CORRUPT", "detail": line[:80], "integrity": "bad"})
            continue
        stored = entry.pop("hash", "")
        expected = _entry_hash(prev, entry)
        entry["integrity"] = "ok" if stored == expected else "TAMPERED"
        prev = stored
        entries.append(entry)
    return entries


def verify_log() -> bool:
    return all(entry.get("integrity") == "ok" for entry in log_entries()) if log_entries() else True
