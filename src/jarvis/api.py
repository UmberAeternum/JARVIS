"""Mark XXVI - app injection: the embeddable local API.

`jarvis serve --api` starts a loopback-only JSON API so other applications
(editor extensions, browser extensions, scripts) can ask UMBRA things.

Auth: every request carries the API token (X-Jarvis-Token header or ?t=).
The token lives in <config>/api-token (0600 on POSIX) and is rotatable with
`jarvis api token rotate`.

Endpoints (all token-gated):
- GET  /health -> {ok, version, tier, brain, model, busy}
- GET  /tools  -> {"tools": [...]} - the registry, tier-gated
- POST /chat   -> {"reply": "..."} - one full agent turn, synchronous
                  (409 when a turn is already running)

Safety: this server binds 127.0.0.1 only - it is the loopback sibling of the
dashboard, not a network listener (the LAN-facing Bridge remains a separate
PRO command). Confirmation-gated tools are auto-DENIED here (an embedded
client cannot answer an interactive gate) and the model is told to point the
user at the dashboard or Bridge. Nothing is logged - least of all the token.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import access as access_module
from . import config

DEFAULT_PORT = 8775
PORT_ATTEMPTS = 20


# ------------------------------------------------------------------ token


def token_path() -> Path:
    return config.config_dir() / "api-token"


def load_token() -> str:
    try:
        return token_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def rotate_token() -> str:
    """Generate a fresh token, store it (0600 on POSIX), return it."""
    token = secrets.token_urlsafe(24)
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    if sys.platform != "win32":
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return token


def ensure_token() -> str:
    return load_token() or rotate_token()


# ------------------------------------------------------------------ state


class ApiState:
    """The full agent for embeddable clients, one turn at a time."""

    def __init__(self, cfg: config.Config):
        from . import licensing
        from .agent import Agent
        from .brain import make_brain_chain
        from .tools import default_registry

        self.cfg = cfg
        self.turn_lock = threading.Lock()
        self.log_lock = threading.Lock()
        self.session_id: int | None = None  # lazy: created on the first turn

        # Confirmation gates cannot be answered by an embedded client, so the
        # API auto-denies them; the tool result tells the model where to send
        # the user instead.
        self.registry = default_registry(
            confirm=self._deny_gated,
            workspace=Path.cwd(),
            allow_screen_control=cfg.vision.screen_control and licensing.is_pro(),
            allow_watchtower=licensing.is_pro(),
        )
        self.agent = Agent(
            make_brain_chain(cfg),
            self.registry,
            max_tool_iterations=cfg.max_tool_iterations,
            max_tokens_per_turn=cfg.max_tokens_per_turn,
        )

    @staticmethod
    def _deny_gated(description: str) -> bool:
        return False

    def run_turn(self, text: str) -> str:
        if not self.turn_lock.acquire(blocking=False):
            raise RuntimeError("busy")
        try:
            reply = self.agent.run_turn(text)
            self._log_turn(text, reply)
            return reply
        finally:
            self.turn_lock.release()

    def _log_turn(self, user_text: str, reply: str) -> None:
        """Conversation-store parity with the CLI and dashboard."""
        try:
            from . import conversations

            with self.log_lock:
                if self.session_id is None:
                    self.session_id = conversations.start_session("API session")
                conversations.log_message(self.session_id, "user", user_text)
                conversations.log_message(self.session_id, "assistant", reply)
        except Exception:
            pass  # logging must never break the conversation


# ---------------------------------------------------------------- handler


def make_handler(state: ApiState) -> type:
    class ApiHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data) -> None:
            self._send(code, json.dumps(data).encode("utf-8"), "application/json")

        def _token(self) -> str:
            if self.headers.get("X-Jarvis-Token"):
                return self.headers.get("X-Jarvis-Token")
            _, _, query = self.path.partition("?")
            for pair in query.split("&"):
                if pair.startswith("t="):
                    return pair[2:]
            return ""

        def _authorized(self) -> bool:
            supplied = self._token()
            expected = load_token()
            return (
                bool(supplied)
                and bool(expected)
                and secrets.compare_digest(supplied, expected)
            )

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            if not self._authorized():
                self._json(403, {"error": "forbidden - missing or invalid API token"})
                return
            path = self.path.split("?")[0].rstrip("/") or "/"
            if path == "/health":
                # read-only /health is the only endpoint that works without
                # the EDITH full-access grant (Mark XXXI)
                from . import __version__, licensing

                self._json(200, {
                    "ok": True,
                    "version": __version__,
                    "tier": licensing.tier(),
                    "brain": state.cfg.brains.primary.provider,
                    "model": state.cfg.brains.primary.model,
                    "busy": state.turn_lock.locked(),
                    "full_access": access_module.full_active(),
                })
                return
            if path == "/tools":
                # Phase 1 spine: the tool listing is an assist-tier capability
                allowed, reason = access_module.authorize("api.tools", actor="api")
                if not allowed:
                    self._json(403, {"error": reason})
                    return
                self._json(200, {"tools": state.registry.descriptions()})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            # Drain the request body BEFORE any early 403: replying with the
            # body unread desyncs HTTP/1.1 keep-alive (the next request on
            # this connection would parse leftover body bytes).
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            if not self._authorized():
                self._json(403, {"error": "forbidden - missing or invalid API token"})
                return
            path = self.path.split("?")[0].rstrip("/") or "/"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"error": "bad JSON"})
                return

            if path == "/chat":
                # Phase 1 spine: chat (and its tools) is an assist-tier capability
                allowed, reason = access_module.authorize("api.chat", actor="api")
                if not allowed:
                    self._json(403, {"error": reason})
                    return
                text = str(payload.get("text", "")).strip()
                if not text:
                    self._json(400, {"error": "empty message"})
                    return
                try:
                    reply = state.run_turn(text)
                except RuntimeError as exc:
                    if str(exc) == "busy":
                        self._json(409, {"error": "a turn is already running"})
                        return
                    self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
                    return
                except Exception as exc:
                    self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
                    return
                access_module.log_append("api_chat", "turn completed (" + str(len(reply)) + " chars)")
                self._json(200, {"reply": reply})
                return
            self._json(404, {"error": "not found"})

        def log_message(self, format: str, *args) -> None:  # silence: no token leakage
            pass

    return ApiHandler


# ----------------------------------------------------------------- server


def start_server(
    state: ApiState, preferred_port: int = DEFAULT_PORT
) -> tuple[ThreadingHTTPServer, int, threading.Thread]:
    """Bind to 127.0.0.1 on the first free port and START serving in a daemon
    thread. Loopback is a hard property of this API - never a LAN listener."""
    last_error: Exception | None = None
    for offset in range(PORT_ATTEMPTS):
        port = preferred_port + offset
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
            break
        except OSError as exc:
            last_error = exc
    else:
        raise RuntimeError(f"no free local port in range: {last_error}")
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def run_api(console) -> int:  # pragma: no cover - interactive loop
    from rich.panel import Panel

    cfg = config.Config.load()
    if cfg is None:
        console.print(
            "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] once "
            "and complete the wizard - the API speaks through that brain."
        )
        return 1
    ensure_token()
    state = ApiState(cfg)
    try:
        server, port, thread = start_server(state)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    console.print(
        Panel(
            f"[bold cyan]http://127.0.0.1:{port}[/]\n\n"
            "Embeddable local API for other apps. Endpoints:\n"
            "  GET  /health   GET  /tools   POST  /chat\n"
            f"token file: {token_path()}  (rotate: [bold]jarvis api token rotate[/])\n\n"
            "[yellow]Loopback only.[/] Gated tools are auto-denied here - use the\n"
            "dashboard or the Bridge for interactive approvals. Ctrl+C stops.",
            title="UMBRA - the API",
            border_style="cyan",
        )
    )
    try:
        while thread.is_alive():
            thread.join(timeout=1.0)
    except KeyboardInterrupt:
        console.print("[dim]API standing down, Sir.[/]")
    finally:
        server.shutdown()
        server.server_close()
    return 0
