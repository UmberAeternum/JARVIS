"""Mark IX - the Bridge: the full desktop agent, reachable from anywhere on
the LAN (phone, headset, another PC).

Architecture:
- Token-gated server bound to the LAN (same model as the portal - a remote
  client is a separate device and cannot reach 127.0.0.1). A random
  per-session token is required on every request; the URL is printed with an
  explicit network-exposure warning and the server stops with Ctrl+C.
- POST /api/command starts an agent turn in a worker thread - the FULL agent
  with all tools, not a stripped chat. Progress flows out as events
  (user/status/tool/reply) that clients long-poll from /api/events.
- The confirmation gate survives the network hop: when a tool needs approval,
  a confirm_request event is emitted and the turn waits up to
  CONFIRM_TIMEOUT_S for POST /api/confirm (the phone shows APPROVE/DENY).
  Timeout or refusal = denied. The gate lives in code, now across the wire.
- One turn at a time; events are capped; conversation-only history is the
  agent's own.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .agent import Agent
from .brain import make_brain_chain
from .serve_page import PAGE_BRIDGE
from .tools import default_registry

DEFAULT_PORT = 8772
CONFIRM_TIMEOUT_S = 120
MAX_EVENTS = 1200  # partial events stream alongside the regular ones
PARTIAL_INTERVAL_S = 0.4  # throttle: one partial event per interval, not per token


class BridgeState:
    """The agent plus the event/confirmation plumbing for remote clients."""

    def __init__(self, cfg, token: str, confirm_timeout: float = CONFIRM_TIMEOUT_S):
        self.token = token
        self.confirm_timeout = confirm_timeout
        self.events: list[dict] = []
        self.events_condition = threading.Condition()
        self.pending: dict[str, dict] = {}
        self.turn_lock = threading.Lock()
        self.turn_running = False

        registry = default_registry(
            confirm=self.confirm,
            allow_screen_control=cfg.vision.screen_control,
        )
        self.registry = registry  # public surface: the agent's tool registry
        chain = make_brain_chain(cfg, on_status=self.push_status)
        self.agent = Agent(
            chain,
            registry,
            on_status=self.push_status,
            max_tool_iterations=cfg.max_tool_iterations,
            max_tokens_per_turn=cfg.max_tokens_per_turn,
        )
        self.push_event("status", {"text": "bridge online"})

    # ---------------------------------------------------------------- events

    def push_event(self, event_type: str, fields: dict | None = None) -> int:
        with self.events_condition:
            event = {"id": len(self.events) + 1, "type": event_type, **(fields or {})}
            self.events.append(event)
            if len(self.events) > MAX_EVENTS:
                del self.events[: len(self.events) - MAX_EVENTS]
            self.events_condition.notify_all()
            return event["id"]

    def events_since(self, since: int) -> list[dict]:
        with self.events_condition:
            return [event for event in self.events if event["id"] > since]

    def wait_for_events(self, since: int, timeout: float) -> list[dict]:
        with self.events_condition:
            if not any(event["id"] > since for event in self.events):
                self.events_condition.wait(timeout=timeout)
            return [event for event in self.events if event["id"] > since]

    def push_status(self, status: str) -> None:
        self.push_event("status", {"text": status})

    # ------------------------------------------------------------------ gate

    def confirm(self, description: str) -> bool:
        """The registry's confirmation callback, bridged to the remote client."""
        confirm_id = "c" + secrets.token_hex(4)
        approved_event = threading.Event()
        with self.events_condition:
            self.pending[confirm_id] = {
                "description": description,
                "result": None,
                "event": approved_event,
            }
        self.push_event("confirm_request", {"confirm_id": confirm_id, "description": description})
        approved = approved_event.wait(timeout=self.confirm_timeout)
        if not approved:
            self.push_event("status", {"text": "confirmation timed out - action denied"})
            return False
        with self.events_condition:
            result = bool(self.pending[confirm_id]["result"])
        self.push_event(
            "status",
            {"text": ("approved: " if result else "denied: ") + description},
        )
        return result

    def answer(self, confirm_id: str, approved: bool) -> bool:
        with self.events_condition:
            pending = self.pending.get(confirm_id)
            if pending is None or pending["result"] is not None:
                return False
            pending["result"] = approved
            pending["event"].set()
            return True

    # ------------------------------------------------------------------ turns

    def run_turn_async(self, text: str) -> dict:
        if not self.turn_lock.acquire(blocking=False):
            return {"error": "a turn is already running"}
        self.turn_running = True
        try:
            self.push_event("user", {"text": text})

            def worker() -> None:
                try:
                    # Mark XXIV - the Bridge streams, same as the dashboard
                    buffer = {"text": ""}
                    last_push = {"at": 0.0}

                    def on_delta(piece: str) -> None:
                        buffer["text"] += piece
                        now = time.monotonic()
                        if now - last_push["at"] >= PARTIAL_INTERVAL_S:
                            last_push["at"] = now
                            self.push_event("partial", {"text": buffer["text"]})

                    reply = self.agent.run_turn(text, on_text_delta=on_delta)
                    self.push_event("reply", {"text": reply})
                except Exception as exc:
                    self.push_event("reply", {"text": f"ERROR: {type(exc).__name__}: {exc}"})
                finally:
                    self.turn_running = False
                    self.turn_lock.release()

            threading.Thread(target=worker, daemon=True).start()
            return {"started": True}
        except Exception:
            self.turn_running = False
            self.turn_lock.release()
            raise


def make_handler(state: BridgeState) -> type:
    class BridgeHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # _send always sets Content-Length

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _token(self) -> str | None:
            if self.headers.get("X-Jarvis-Token"):
                return self.headers.get("X-Jarvis-Token")
            query = self.path.partition("?")[2]
            for pair in query.split("&"):
                if pair.startswith("t="):
                    return pair[2:]
            return None

        def _authorized(self) -> bool:
            token = self._token()
            return bool(token) and secrets.compare_digest(token, state.token)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            path, _, query = self.path.partition("?")
            path = path.rstrip("/") or "/"
            if not self._authorized() and path != "/":
                self._send(403, b"forbidden - missing session token", "text/plain")
                return
            if path == "/":
                if not self._authorized():
                    self._send(403, b"bridge requires the session token", "text/plain")
                    return
                self._send(200, PAGE_BRIDGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/events":
                since = 0
                for pair in query.split("&"):
                    if pair.startswith("since="):
                        since = int(pair[6:] or 0)
                events = state.wait_for_events(since, timeout=25.0)
                last = events[-1]["id"] if events else since
                self._send(200, json.dumps({"events": events, "last": last}).encode("utf-8"),
                           "application/json")
                return
            if path == "/api/status":
                self._send(
                    200,
                    json.dumps({"turn_running": state.turn_running}).encode("utf-8"),
                    "application/json",
                )
                return
            if path == "/api/history":
                # Mark XXII - the Record: the Second Mind reaches the phone
                from .conversations import list_sessions

                self._send(
                    200,
                    json.dumps({"sessions": list_sessions(20)}).encode("utf-8"),
                    "application/json",
                )
                return
            if path == "/api/session":
                from .conversations import session_messages

                sid = 0
                for pair in query.split("&"):
                    if pair.startswith("id="):
                        sid = int(pair[3:] or 0)
                self._send(
                    200,
                    json.dumps({"messages": session_messages(sid)}).encode("utf-8"),
                    "application/json",
                )
                return
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            path = self.path.split("?")[0]
            if not self._authorized():
                self._send(403, b"forbidden - missing session token", "text/plain")
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._send(400, json.dumps({"error": "bad JSON"}).encode("utf-8"), "application/json")
                return

            if path == "/api/command":
                text = str(payload.get("text", "")).strip()
                if not text:
                    self._send(400, json.dumps({"error": "empty command"}).encode("utf-8"),
                               "application/json")
                    return
                result = state.run_turn_async(text)
                code = 200 if "started" in result else 409
                self._send(code, json.dumps(result).encode("utf-8"), "application/json")
                return
            if path == "/api/confirm":
                answered = state.answer(
                    str(payload.get("confirm_id", "")), bool(payload.get("approved", False))
                )
                self._send(
                    200 if answered else 404,
                    json.dumps({"answered": answered}).encode("utf-8"),
                    "application/json",
                )
                return
            self._send(404, b"not found", "text/plain")

        def log_message(self, format: str, *args) -> None:  # silence default logging
            pass

    return BridgeHandler


def start_server(
    state: BridgeState, preferred_port: int = DEFAULT_PORT
) -> tuple[ThreadingHTTPServer, int, threading.Thread]:
    """Bind to the LAN on the first free port and START serving in a daemon
    thread. Returns (server, port, thread)."""
    last_error: Exception | None = None
    for offset in range(10):
        port = preferred_port + offset
        try:
            server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(state))
            break
        except OSError as exc:
            last_error = exc
    else:
        raise RuntimeError(f"no free port in range: {last_error}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def run_bridge(console) -> int:  # pragma: no cover - interactive loop
    from rich.panel import Panel

    from .portal import lan_address  # lazy: portal imports BridgeState from here

    cfg = config.Config.load()
    if cfg is None:
        console.print(
            "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] once "
            "and complete the wizard - the bridge exposes that brain."
        )
        return 1
    token = secrets.token_urlsafe(6)
    state = BridgeState(cfg, token)
    try:
        server, port, _thread = start_server(state)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    url = f"http://{lan_address()}:{port}/?t={token}"
    console.print(
        Panel(
            f"[bold cyan]{url}[/]\n\n"
            "Open it on your phone (or any device on this network): the full "
            "agent - all tools - with confirmations delivered to you as "
            "APPROVE/DENY buttons.\n"
            f"brain: {cfg.brains.primary.provider} ({cfg.brains.primary.model})\n\n"
            "[yellow]Security:[/] the bridge is now reachable from your local "
            "network and gated only by this session token. It stops with Ctrl+C.",
            title="J.A.R.V.I.S. - the Bridge",
            border_style="cyan",
        )
    )
    try:
        while _thread.is_alive():
            _thread.join(timeout=1.0)
    except KeyboardInterrupt:
        console.print("[dim]Bridge standing down, Sir.[/]")
    finally:
        server.shutdown()
        server.server_close()
    return 0
