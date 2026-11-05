"""Mark XVII - the Update Checker: signed manifest, report only.

Fetches a signed update manifest through the SSRF-guarded fetcher, verifies
its Ed25519 signature with the same public key that validates PRO licenses,
and REPORTS a newer release. Nothing is ever downloaded or installed
automatically - the user decides what to do with the release URL.

Manifest shape:
    {"payload": {"version": "3.4.0", "channel": "stable", "notes": "...",
                 "url": "https://...", "pro_url": "https://..."},
     "signature": "<base64 Ed25519 over canonical payload JSON>"}

The signature covers the canonical JSON serialization of the payload
(sort_keys + tight separators), so formatting differences on the wire cannot
confuse verification. Offline-safe by design: every failure mode returns a
reason string, never an exception.
"""

from __future__ import annotations

import base64
import json

from . import licensing, safety

DEFAULT_MANIFEST_URL = (
    # raw.githubusercontent serves the file with a direct 200 - release-asset
    # URLs 302-redirect to storage, and the guarded fetcher refuses redirects
    "https://raw.githubusercontent.com/UmberAeternum/JARVIS/main/umbra-manifest.json"
)
MAX_MANIFEST_BYTES = 64 * 1024  # a manifest is tiny; anything larger is hostile


def canonical_payload_bytes(payload: dict) -> bytes:
    """The exact bytes the Ed25519 signature covers."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_manifest(manifest: dict) -> bool:
    """True only when the manifest carries a valid signature from the publisher."""
    payload = manifest.get("payload")
    signature_b64 = manifest.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature_b64, str):
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(licensing.PUBLIC_KEY_B64)
        )
        public_key.verify(base64.b64decode(signature_b64), canonical_payload_bytes(payload))
        return True
    except Exception:  # InvalidSignature, binascii.Error, ValueError, ImportError
        return False


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.strip().lstrip("vV").split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(current: str, candidate: str) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def check_for_update(
    current_version: str, manifest_url: str = "", timeout: float = 4.0
) -> dict:
    """Fetch + verify the manifest and report. Never raises; offline-safe.

    LITE sees stable-channel releases; PRO-channel releases and the pro_url
    asset are surfaced only to PRO tiers.
    """
    url = manifest_url or DEFAULT_MANIFEST_URL
    try:
        data, reason = safety.guarded_fetch_bytes(url, MAX_MANIFEST_BYTES, timeout=timeout)
    except Exception as exc:
        return {
            "update_available": False,
            "reason": f"manifest fetch failed: {type(exc).__name__}: {exc}",
        }
    if data is None:
        return {"update_available": False, "reason": f"manifest fetch failed: {reason}"}
    try:
        manifest = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return {"update_available": False, "reason": f"manifest not valid JSON: {exc}"}
    if not isinstance(manifest, dict) or not verify_manifest(manifest):
        return {"update_available": False, "reason": "manifest signature invalid or malformed"}
    payload = manifest["payload"]
    channel = str(payload.get("channel", "stable"))
    if channel == "pro" and licensing.tier() != "pro":
        return {"update_available": False, "reason": "PRO-channel release skipped (LITE tier)"}
    latest = str(payload.get("version", "")).strip()
    if not latest:
        return {"update_available": False, "reason": "manifest has no version"}
    if not is_newer(current_version, latest):
        return {"update_available": False, "reason": "up to date", "latest": latest}
    result = {
        "update_available": True,
        "latest": latest,
        "notes": str(payload.get("notes", "")),
        "url": str(payload.get("url", "")),
        "channel": channel,
    }
    if licensing.tier() == "pro" and payload.get("pro_url"):
        result["pro_url"] = str(payload["pro_url"])
    return result
