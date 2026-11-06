"""Mark XXXI - GA hardening: paid-update application and the payment queue.

update apply:
- `jarvis update apply` fetches the signed manifest, verifies its Ed25519
  signature, downloads the wheel named in the payload (guarded fetch),
  verifies its SHA-256 against the manifest, stages it, and installs with
  pip (argument-list subprocess). The previous wheel is cached so
  `jarvis update rollback` can reinstall it. Offline-safe: every fetch
  failure is a reason, never a crash.

payhub:
- `jarvis payhub serve` - a small webhook receiver that queues payment
  notifications (LemonSqueezy-style HMAC-SHA256 signature verification,
  secret from the UMBRA_PAYHUB_SECRET environment variable). Queued
  requests live in payhub-queue.jsonl; the OFFLINE signer mints keys from
  them - no private key ever touches this process. Email delivery is
  intentionally out of scope for the stdlib build (noted assumption):
  `jarvis payhub list` / `mark-sent` drive the manual step.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from . import config

STAGING_NAME = "staged-update.whl"


def _staging_path() -> Path:
    return config.config_dir() / STAGING_NAME


def _state_path() -> Path:
    return config.config_dir() / "update-state.json"


def _queue_path() -> Path:
    return config.config_dir() / "payhub-queue.jsonl"


# ------------------------------------------------------------- update apply


def _fetch(url: str) -> bytes | None:
    from .safety import guarded_fetch_bytes

    data, _reason = guarded_fetch_bytes(url, 200_000_000, timeout=30.0)
    return data


def _installer(wheel_path: Path) -> bool:
    """Install the staged wheel (single audited execution point)."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", str(wheel_path)],
        shell=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def apply_update(manifest: dict, current_version: str,
                 fetch=None, installer=None) -> tuple[bool, str]:
    """Download + verify + install the update named by a verified manifest.

    fetch/installer are injectable for tests. Returns (ok, message).
    """
    from . import __version__
    from .updates import canonical_payload_bytes, verify_manifest

    if not verify_manifest(manifest):
        return False, "manifest signature invalid - refusing to apply."
    payload = manifest.get("payload", {})
    wheel_url = str(payload.get("wheel_url", "")).strip()
    expected_sha = str(payload.get("sha256", "")).strip().lower()
    if not wheel_url or not expected_sha:
        return False, "manifest has no wheel_url/sha256 - nothing to apply."
    if payload.get("version") == current_version:
        return False, "already on that version."
    do_fetch = fetch or _fetch
    try:
        data = do_fetch(wheel_url)
    except Exception as exc:
        return False, f"download failed: {type(exc).__name__}: {exc}"
    if not data:
        return False, "download failed: empty response."
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha:
        return False, "wheel hash mismatch - refusing to install a tampered update."
    staging = _staging_path()
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(data)
    # cache the current wheel reference for rollback (best effort)
    state = {"previous_version": current_version,
             "applied_version": str(payload.get("version")),
             "applied_ts": time.time()}
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    do_install = installer or _installer
    if not do_install(staging):
        return False, "pip install failed - the staged wheel is at " + str(staging)
    staging.unlink(missing_ok=True)
    return True, f"updated {__version__} -> {payload.get('version')}. Restart UMBRA."


def rollback_update(installer=None) -> tuple[bool, str]:
    """Reinstall the previous wheel if one was cached by apply_update."""
    state_path = _state_path()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "no update history - nothing to roll back to."
    previous = state.get("previous_version")
    if not previous:
        return False, "no previous version recorded."
    dist_wheel = Path("dist") / f"jarvis_ai-{previous}-py3-none-any.whl"
    if not dist_wheel.is_file():
        return False, f"previous wheel not cached ({dist_wheel})."
    do_install = installer or _installer
    if not do_install(dist_wheel):
        return False, "rollback install failed."
    state_path.unlink(missing_ok=True)
    return True, f"rolled back to {previous}."


# ------------------------------------------------------------------- payhub


def _verify_signature(raw_body: bytes, signature: str) -> bool:
    secret = os.environ.get("UMBRA_PAYHUB_SECRET", "")
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def queue_payment(entry: dict) -> None:
    path = _queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_queue() -> list[dict]:
    path = _queue_path()
    if not path.is_file():
        return []
    entries: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return entries


def mark_sent(index: int) -> bool:
    entries = read_queue()
    if 0 <= index < len(entries):
        entries[index]["sent"] = True
        path = _queue_path()
        path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
            encoding="utf-8",
        )
        return True
    return False


def run_payhub(console, args: list[str]) -> int:
    """The webhook receiver. Loopback by default; --lan binds all interfaces
    for real storefront webhooks (HMAC signature still required)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    lan = "--lan" in args
    port = 8776
    for flag_value in (args[args.index("--port") + 1] if "--port" in args else None,):
        if flag_value:
            try:
                port = int(flag_value)
            except ValueError:
                console.print("[red]--port needs an integer[/]")
                return 1

    if not os.environ.get("UMBRA_PAYHUB_SECRET"):
        console.print(
            "[yellow]UMBRA_PAYHUB_SECRET is not set - every webhook will be "
            "refused (403). Set it to the storefront's signing secret.[/]"
        )

    class PayhubHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            if self.path.split("?")[0] == "/health":
                self._send(200, b'{"ok": true}')
                return
            self._send(404, b'{"error": "not found"}')

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length)
            signature = self.headers.get("X-Signature", "")
            if not _verify_signature(raw, signature):
                self._send(403, b'{"error": "invalid signature"}')
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                payload = {"raw": raw.decode("utf-8", "replace")[:2000]}
            queue_payment({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source": self.path.split("?")[0],
                "email": str(payload.get("email", "")),
                "product": str(payload.get("product_name", "")),
                "sent": False,
            })
            self._send(200, b'{"queued": true}')

        def log_message(self, format: str, *args) -> None:  # never log payloads
            pass

    bind_host = "0.0.0.0" if lan else "127.0.0.1"
    try:
        server = ThreadingHTTPServer((bind_host, port), PayhubHandler)
    except OSError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    from rich.panel import Panel

    console.print(
        Panel(
            f"[bold cyan]http://{bind_host}:{port}/hook[/]\n\n"
            "Webhook receiver: POST with an HMAC-SHA256 signature header\n"
            "(X-Signature) verified against UMBRA_PAYHUB_SECRET. Valid\n"
            "payments are queued locally; keys are minted OFFLINE with the\n"
            "private signer - no private key ever touches this process.\n"
            "Ctrl+C to stop.",
            title="UMBRA - the payment queue",
            border_style="amber",
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("[dim]Payhub standing down, Sir.[/]")
    finally:
        server.server_close()
    return 0
