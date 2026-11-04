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
import json
from datetime import datetime, timezone
from pathlib import Path

from . import config

PREFIX = "UMBRA-"

# The public half of the signing key. The private half lives only with the
# publisher (umbra-private/make_license.py) and is never shipped.
PUBLIC_KEY_B64 = "weuy0xF1xIxpnAqG+cR1hP2DG/I17ILlAYptdjbTE60="


def _license_path() -> Path:
    # resolved through the config module so tests can redirect the directory
    return config.config_dir() / "license.key"


def stored_key() -> str:
    path = _license_path()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def install_license(key: str) -> tuple[bool, str]:
    """Validate and store a PRO license key. Returns (ok, message)."""
    payload, reason = validate_license(key)
    if payload is None:
        return False, reason
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
    return data, None


def tier() -> str:
    """'pro' when a valid PRO license is installed, else 'lite'."""
    payload, _reason = validate_license(stored_key())
    return "pro" if payload is not None else "lite"


def is_pro() -> bool:
    return tier() == "pro"
