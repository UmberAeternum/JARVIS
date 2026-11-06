"""UMBRA licensing - Ed25519-signed PRO keys, freemium tiers.

LITE (free, no license needed): chat, voice, memory, reminders + Sentinel,
health logging and screening, /look, avatar, web search, files, apps.
PRO (paid license key): screen control, Bridge (jarvis serve), Portal (XR),
Watchtower, live vision.

Keys are signed with an Ed25519 private key that never ships - the product
verifies with the embedded public half only. A forged or tampered key fails
the signature check; expired keys fail the date check. This is strong
honest licensing, not DRM theater: it will not stop a determined cracker
who patches the binary, and we say so in the EULA.

The license key itself is stored in the user's config directory
(license.key) - one file, local only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

PREFIX = "UMBRA-"

# The public half of the signing key. The private half lives only with the
# publisher (umbra-private/make_license.py) and is never shipped.
PUBLIC_KEY_B64 = "weuy0xF1xIxpnAqG+cR1hP2DG/I17ILlAYptdjbTE60="

TRIAL_DAYS = 7


def _license_path() -> Path:
    # resolved through the config module so tests can redirect the directory
    return config.config_dir() / "license.key"


def _revoked_path() -> Path:
    return config.config_dir() / "revoked.txt"


def _activations_path() -> Path:
    return config.config_dir() / "activations.json"


def _trial_path() -> Path:
    return config.config_dir() / "trial.json"


def stored_key() -> str:
    path = _license_path()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _key_digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _is_revoked(key: str) -> bool:
    """Mark XXXI: the revocation list. revoked.txt holds one sha256 hex digest
    (or full key) per line; checked at activation and at runtime."""
    path = _revoked_path()
    if not path.is_file():
        return False
    try:
        digest = _key_digest(key.strip())
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line == key.strip() or line.lower() == digest:
                return True
    except OSError:
        return False
    return False


def start_trial() -> tuple[bool, str]:
    """Mark XXXI: a local, time-boxed PRO trial (TRIAL_DAYS). Honest scope:
    local-trust only - a determined user can reset it, and the EULA says the
    trial is for evaluation. Returns (ok, message)."""
    path = _trial_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            from .access import device_fingerprint

            if data.get("fingerprint") == device_fingerprint():
                expires = float(data.get("expires_ts", 0))
                if time.time() < expires:
                    days = int((expires - time.time()) // 86400)
                    return False, f"trial already running - {days} day(s) left."
                return False, "the trial on this device has already been used."
        except (OSError, ValueError):
            pass
    from .access import device_fingerprint

    now = time.time()
    state = {"start_ts": now, "expires_ts": now + TRIAL_DAYS * 86400,
             "fingerprint": device_fingerprint()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return True, f"PRO trial started - {TRIAL_DAYS} days, full access, on this device."


def _trial_active() -> bool:
    try:
        data = json.loads(_trial_path().read_text(encoding="utf-8"))
        from .access import device_fingerprint

        return (
            data.get("fingerprint") == device_fingerprint()
            and time.time() < float(data.get("expires_ts", 0))
        )
    except (OSError, ValueError):
        return False


def install_license(key: str) -> tuple[bool, str]:
    """Validate and store a PRO license key. Returns (ok, message)."""
    payload, reason = validate_license(key)
    if payload is None:
        return False, reason
    # Mark XXXI: device binding + max_devices at activation time
    from .access import device_fingerprint

    fingerprint = device_fingerprint()
    max_devices = payload.get("max_devices")
    activations: dict = {}
    try:
        activations = json.loads(_activations_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        activations = {}
    digest = _key_digest(key.strip())
    seen: list = [fp for fp in activations.get(digest, []) if fp != fingerprint]
    try:
        max_devices_int = int(max_devices) if max_devices is not None else None
    except (TypeError, ValueError):
        max_devices_int = None
    if max_devices_int is not None and len(seen) >= max_devices_int:
        return False, (
            f"license device limit reached ({max_devices_int} devices) - "
            "contact the publisher to move a device."
        )
    seen.append(fingerprint)
    activations[digest] = seen
    _activations_path().parent.mkdir(parents=True, exist_ok=True)
    _activations_path().write_text(json.dumps(activations, indent=2), encoding="utf-8")
    if _is_revoked(key):
        return False, "this license key has been revoked."
    path = _license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.strip(), encoding="utf-8")
    licensed_to = payload.get("name", "")
    return True, f"PRO license installed - licensed to {licensed_to}."


def validate_license(key: str) -> tuple[dict | None, str | None]:
    """(payload, None) for a valid PRO license; (None, reason) otherwise."""
    key = (key or "").strip()
    if not key.startswith(PREFIX):
        return None, "not a UMBRA license key"
    if _is_revoked(key):
        return None, "this license key has been revoked."
    try:
        payload_b64, signature_b64 = key[len(PREFIX):].split(".", 1)
    except ValueError:
        return None, "malformed license key"
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        payload = base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4))
        signature = base64.urlsafe_b64decode(signature_b64 + "=" * (-len(signature_b64) % 4))
        public_raw = base64.b64decode(PUBLIC_KEY_B64)
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, payload)
        data = json.loads(payload.decode("utf-8"))
    except InvalidSignature:
        return None, "license signature is invalid"
    except Exception as exc:
        return None, f"license could not be read: {exc}"
    if data.get("tier") != "pro":
        return None, "license is not a PRO license"
    expiry = data.get("exp")
    if expiry:
        try:
            if datetime.now(timezone.utc).date() > datetime.strptime(expiry, "%Y-%m-%d").date():
                return None, f"license expired on {expiry}"
        except ValueError:
            return None, "license has an unreadable expiry date"
    # Mark XXXI: device binding - a key pinned to a device only works there
    bound = data.get("device_id")
    if bound:
        from .access import device_fingerprint

        if bound != device_fingerprint():
            return None, "this license is bound to a different device."
    return data, None


def tier() -> str:
    """'pro' when a valid PRO license is installed or a trial is running."""
    payload, _reason = validate_license(stored_key())
    if payload is not None:
        return "pro"
    if _trial_active():
        return "pro"
    return "lite"


def is_pro() -> bool:
    return tier() == "pro"
