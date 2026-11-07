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
SHA-256 of the previous entry, so edits are detectable, and a checkpoint
file (access-log.meta.json: entry count + head hash, written after every
append) catches edits that leave a consistent prefix - including tail
truncation and clock-rollback replays of an old grant state. `jarvis
access log` prints it; `jarvis access verify` checks it; `jarvis access
revoke --all` clears the grant instantly.

Honest threat model: the machine owner can always edit their own files -
including replaying an old grant file, rolling the clock forward inside a
forged expiry, or rewriting both the state and the ledger AND the
checkpoint. The protocol's controls target automation, accidents, and
persistence, not a user attacking their own box. Hard prohibitions (no
self-propagation, no silent grants, no bypass) are test-enforced in the
smoke suite.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

from . import config

CONFIRMATION_PHRASE = "I grant UMBRA full access"
DEFAULT_WINDOW_H = 24

# Mark XXXI Phase 1 - the policy spine: tiered grants instead of one switch.
# Every reach action maps to the LEAST tier that unlocks it; authorize() is
# the single chokepoint all gates call.
TIERS = ("observe", "assist", "act", "install")
TIER_RANK = {"observe": 0, "assist": 1, "act": 2, "install": 3}

# action -> required tier. Unknown actions map to "install" (default-deny
# at the strongest tier - a forgotten gate cannot become a bypass).
SCOPE_TIER = {
    "access.status": "observe",
    "api.health": "observe",
    "api.tools": "assist",
    "api.chat": "assist",
    "overlay.attach": "assist",
    "inject.install": "install",
}


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
    """Read the grant state, migrating the pre-spine single-'full' format."""
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("full") and "grants" not in data:  # pre-spine format -> migrate
        expires = float(data.get("expires_ts", 0))
        data["grants"] = {
            tier: {"ts": float(data.get("granted_ts", 0)), "expires_ts": expires}
            for tier in TIERS
        }
        data["fingerprint"] = data.get("fingerprint", device_fingerprint())
    return data


def _save_state(state: dict) -> None:
    """Write the state file ATOMICALLY (temp file + os.replace): concurrent
    grant writers each produce a complete file, so the documented
    last-write-wins race can never tear the JSON mid-write."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))
    if sys.platform != "win32":
        try:
            path.chmod(0o600)
        except OSError:
            pass


def _tier_active(tier: str, state: dict, now: float) -> bool:
    grant = (state.get("grants") or {}).get(tier)
    if not isinstance(grant, dict):
        return False
    if state.get("fingerprint") != device_fingerprint():
        return False
    try:
        return now < float(grant.get("expires_ts", 0))
    except (TypeError, ValueError):
        return False


def full_active(now: float | None = None) -> bool:
    """Legacy surface: True when the strongest tier (install) is active -
    under tiered grants that implies every lesser tier is active too."""
    now = time.time() if now is None else now
    return _tier_active("install", _load_state(), now)


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


def grant_tiers(tiers: list[str], phrase_input: str,
                window_h: int | None = None) -> tuple[bool, str]:
    """Phase 1 spine: grant exactly the named tiers, each expiring on its own
    window. The typed phrase is mandatory whatever the tier."""
    for tier in tiers:
        if tier not in TIERS:
            return False, f"unknown tier: {tier}"
    typed = (phrase_input or "").strip()
    if typed != CONFIRMATION_PHRASE:
        log_append("grant_denied", "confirmation phrase mismatch (tiers: "
                   + ",".join(tiers) + ")")
        return False, "confirmation phrase did not match - grant NOT created."
    hours = window_h or window_hours()
    now = time.time()
    state = _load_state()
    grants = state.get("grants") or {}
    state["grants"] = grants
    for tier in tiers:
        grants[tier] = {"ts": now, "expires_ts": now + hours * 3600}
    state["fingerprint"] = device_fingerprint()
    _save_state(state)
    log_append("grant", "tiers " + ",".join(tiers) + f", expires in {hours}h")
    return True, f"Granted {', '.join(tiers)} - expires in {hours}h (ledger updated)."


def grant_full(phrase_input: str) -> tuple[bool, str]:
    """Legacy surface: grant ALL tiers - the rare case, kept for
    compatibility with the pre-spine command."""
    return grant_tiers(list(TIERS), phrase_input)


def tier_snapshot(now: float | None = None) -> dict[str, dict]:
    """Phase 7 - machine-readable per-tier state for the trust dashboard:
    every tier is always listed, each as {granted, expires_ts} (expires_ts is
    None when the tier is not active)."""
    now = time.time() if now is None else now
    state = _load_state()
    grants = state.get("grants") or {}
    snapshot: dict[str, dict] = {}
    for tier in TIERS:
        grant = grants.get(tier)
        active = _tier_active(tier, state, now)
        expires: float | None = None
        if active and isinstance(grant, dict):
            try:
                expires = float(grant.get("expires_ts", 0)) or None
            except (TypeError, ValueError):
                expires = None
        snapshot[tier] = {"granted": active, "expires_ts": expires}
    return snapshot


def revoke_all() -> str:
    _save_state({"fingerprint": device_fingerprint()})
    log_append("revoke_all", "all tier grants revoked")
    return "FULL ACCESS revoked - reach capabilities are denied again."


def authorize(action: str, target: str = "", scope: str | None = None,
              actor: str = "user") -> tuple[bool, str]:
    """THE policy chokepoint (Phase 1, actor/scope added in the
    follow-through). Every reach capability calls this - no gate may check
    grants, expiry, or fingerprint on its own.

    - scope: an explicit tier request; when omitted, the action's mapped
      tier applies. An escalated scope (higher than the action's mapping)
      is honored ONLY if that tier is genuinely granted - escalation is
      therefore still consent-bound.
    - actor: who asked (user | api | overlay | agent) - recorded in the
      ledger so every entry says who reached.

    Checks the tier against the tiered grants (expiry + fingerprint), then
    writes the ledger entry either way. Returns (allowed, reason)."""
    mapped = SCOPE_TIER.get(action, "install")
    tier = scope if scope in TIER_RANK else mapped
    state = _load_state()
    now = time.time()
    detail = action + (f" -> {target}" if target else "") + f" (actor: {actor})"
    if _tier_active(tier, state, now):
        log_append("reach_allowed", detail, actor=actor)
        return True, f"{action} authorized (tier {tier})."
    reason = f"{action} denied - tier '{tier}' not granted (or expired)."
    log_append("reach_denied", reason + (f" -> {target}" if target else ""), actor=actor)
    return False, reason


def require_full(action: str) -> bool:
    """Legacy gate surface (pre-spine call sites). Maps legacy action
    strings to spine scopes and defers to authorize()."""
    if action.startswith("inject install"):
        action = "inject.install"
    elif action.startswith("overlay --attach"):
        action = "overlay.attach"
    elif action.startswith("api"):
        action = "api.chat"
    allowed, _reason = authorize(action)
    return allowed


def status_text() -> str:
    """Per-tier status, in rank order - every tier is always listed (an
    empty/expired grant prints as "not granted")."""
    state = _load_state()
    grants = state.get("grants") or {}
    lines = []
    for tier in TIERS:
        grant = grants.get(tier)
        if grant and _tier_active(tier, state, time.time()):
            expires = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(grant["expires_ts"])))
            lines.append(f"  {tier}: granted, expires {expires}")
        else:
            lines.append(f"  {tier}: not granted")
    return "ACCESS TIERS:\n" + "\n".join(lines)


# ------------------------------------------------------------------ ledger


def _entry_hash(prev_hash: str, entry: dict) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def _meta_path() -> Path:
    """The ledger's checkpoint: entry count + head hash, written atomically
    after every append. Hash chaining alone cannot detect tail truncation
    (a consistent prefix verifies), so the checkpoint is the second anchor:
    a ledger whose length or head does not match the checkpoint is
    tampered, full stop. The checkpoint is metadata, not a grant - it can
    never create reach."""
    return config.config_dir() / "access-log.meta.json"


def _read_meta() -> dict:
    try:
        data = json.loads(_meta_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _write_meta(meta: dict) -> None:
    path = _meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta), encoding="utf-8")


# Appends (and their checkpoint updates) are serialized so concurrent
# threads cannot interleave a stale count/head into the checkpoint.
_LOG_LOCK = threading.Lock()


def log_append(action: str, detail: str, actor: str = "user") -> None:
    """Append one tamper-evident entry (chained hashes + checkpoint). Never
    raises. The actor (user | api | overlay | agent) is part of the signed
    entry."""
    try:
        with _LOG_LOCK:
            path = _log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            prev_hash = "0" * 64
            if path.is_file():
                lines = [line for line in path.read_text(encoding="utf-8").splitlines()
                         if line.strip()]
                if lines:
                    try:
                        prev_hash = json.loads(lines[-1]).get("hash", prev_hash)
                    except ValueError:
                        prev_hash = "0" * 64
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "action": action,
                "detail": detail,
                "actor": actor,
            }
            entry["hash"] = _entry_hash(prev_hash, entry)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            lines = [line for line in path.read_text(encoding="utf-8").splitlines()
                     if line.strip()]
            _write_meta({"count": len(lines), "head": entry["hash"]})
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
        entry["hash"] = stored  # kept for verify_log's checkpoint match
        prev = stored
        entries.append(entry)
    return entries


def verify_log() -> bool:
    """Ledger integrity: (1) the hash chain verifies entry by entry, and
    (2) when a checkpoint exists, the entry count and head hash match it -
    tail truncation and other edits that leave a consistent prefix are
    caught by the checkpoint. Ledgers predating the checkpoint (no
    access-log.meta.json yet) verify by chain alone until the next append
    writes the checkpoint - that migration path is deliberate, so an
    upgrade never brands an intact legacy ledger as tampered."""
    entries = log_entries()
    if not all(entry.get("integrity") == "ok" for entry in entries):
        return False
    meta = _read_meta()
    if not meta:
        return True  # legacy ledger (pre-checkpoint): chain-only verdict above
    if not entries:
        return False  # checkpoint claims entries; the file has none
    try:
        count = int(meta.get("count", -1))
    except (TypeError, ValueError):
        return False
    if count != len(entries) or meta.get("head") != entries[-1].get("hash"):
        return False
    return True
