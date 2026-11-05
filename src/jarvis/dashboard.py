"""Mark XVI - the Dashboard: a local web mission control for UMBRA.

A single-page dashboard served at 127.0.0.1 only (never exposed to the
network). Tabbed interface: Chat, Health (the Oracle), Memory (the second
brain), Kanban, Watch rules, and Settings — every subsystem visual and
clickable instead of CLI-only.

Mark XXI: the console tab runs the FULL agent — all tools, the same
confirmation gate as the CLI, delivered in the browser as APPROVE/DENY
buttons (the Mark IX bridge pattern, minus the network: no token, loopback
only). Progress flows out as events (user/status/confirm_request/reply)
that the page polls from /api/events. Every turn is logged to the local
conversation store exactly like the CLI does.

All subsystem imports happen lazily inside handler methods (the established
pattern), so the module can be imported without triggering the full stack.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config
from .dashboard_page import PAGE

DEFAULT_PORT = 8773
PORT_ATTEMPTS = 20
CONFIRM_TIMEOUT_S = 120
MAX_EVENTS = 1200  # partial events stream alongside the regular ones
PARTIAL_INTERVAL_S = 0.4  # throttle: one partial event per interval, not per token


class DashboardState:
    """The full agent plus the event/confirmation plumbing for the local UI."""

    def __init__(self, cfg):
        from . import licensing
        from .tools import default_registry

        self.cfg = cfg
        self.events: list[dict] = []
        self.events_condition = threading.Condition()
        self.pending: dict[str, dict] = {}
        self.turn_lock = threading.Lock()
        self.turn_running = False
        self.session_id: int | None = None  # lazy: created on the first turn
        self.confirm_timeout = CONFIRM_TIMEOUT_S
        self.log_lock = threading.Lock()

        self.registry = default_registry(
            confirm=self.confirm,
            workspace=Path.cwd(),
            allow_screen_control=cfg.vision.screen_control and licensing.is_pro(),
            allow_watchtower=licensing.is_pro(),
        )
        from .agent import Agent
        from .brain import make_brain_chain

        chain = make_brain_chain(cfg, on_status=self.push_status)
        self.agent = Agent(
            chain,
            self.registry,
            on_status=self.push_status,
            max_tool_iterations=cfg.max_tool_iterations,
            max_tokens_per_turn=cfg.max_tokens_per_turn,
        )
        self.push_event("status", {"text": "dashboard online"})

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
        """The registry's confirmation callback, bridged to the browser."""
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
                reply = None
                try:
                    # Mark XXIII - the living reply: stream progress to the page
                    buffer = {"text": ""}
                    last_push = {"at": 0.0}

                    def on_delta(piece: str) -> None:
                        buffer["text"] += piece
                        now = time.monotonic()
                        if now - last_push["at"] >= PARTIAL_INTERVAL_S:
                            last_push["at"] = now
                            self.push_event("partial", {"text": buffer["text"]})

                    reply = self.agent.run_turn(text, on_text_delta=on_delta)
                    # flush whatever the throttle held back so the streamed
                    # bubble ends up showing the whole reply
                    if buffer["text"]:
                        self.push_event("partial", {"text": buffer["text"]})
                    self.push_event("reply", {"text": reply})
                except Exception as exc:
                    reply = f"ERROR: {type(exc).__name__}: {exc}"
                    self.push_event("reply", {"text": reply})
                finally:
                    # the turn is over once the reply is out - the next turn
                    # must not wait behind post-turn logging housekeeping
                    self.turn_running = False
                    self.turn_lock.release()
                self._log_turn(text, reply)

            threading.Thread(target=worker, daemon=True).start()
            return {"started": True}
        except Exception:
            self.turn_running = False
            self.turn_lock.release()
            raise

    def _log_turn(self, user_text: str, reply: str) -> None:
        """Mark XV parity: dashboard turns land in the conversation store too."""
        try:
            from . import conversations

            with self.log_lock:  # runs outside the turn lock - serialize it
                if self.session_id is None:
                    self.session_id = conversations.start_session("Dashboard session")
                conversations.log_message(self.session_id, "user", user_text)
                conversations.log_message(self.session_id, "assistant", reply)
        except Exception:
            pass  # logging must never break the conversation


def make_handler(state: DashboardState) -> type:
    class DashboardHandler(BaseHTTPRequestHandler):
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

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            path, _, query = self.path.partition("?")
            path = path.rstrip("/") or "/"
            if path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return

            if path == "/api/events":
                since = 0
                for pair in query.split("&"):
                    if pair.startswith("since="):
                        since = int(pair[6:] or 0)
                events = state.wait_for_events(since, timeout=10.0)
                last = events[-1]["id"] if events else since
                self._json(200, {"events": events, "last": last})
                return

            if path == "/api/status":
                self._json(200, {"turn_running": state.turn_running})
                return

            if path == "/api/state":
                from . import licensing

                cfg = state.cfg
                self._json(200, {
                    "version": _version(),
                    "tier": licensing.tier(),
                    "provider": cfg.brains.primary.provider,
                    "model": cfg.brains.primary.model,
                    "hasKey": bool(cfg.brains.primary.api_key),
                })
                return

            if path == "/api/memory":
                from .memory import recent_notes

                self._json(200, {"memories": recent_notes(50)})
                return

            if path == "/api/health":
                from .health import risk_assessment

                report = risk_assessment()
                self._send(200, report.encode("utf-8"), "text/plain; charset=utf-8")
                return

            if path == "/api/kanban":
                from .portal import load_board

                self._json(200, load_board())
                return

            if path == "/api/watch":
                from .watchtower import load_rules

                self._json(200, {"rules": load_rules()})
                return

            if path == "/api/history":
                from .conversations import list_sessions

                self._json(200, {"sessions": list_sessions(20)})
                return

            if path == "/api/session":
                # Mark XXII - the Record: read one session's messages
                from .conversations import session_messages

                sid = 0
                for pair in query.split("&"):
                    if pair.startswith("id="):
                        sid = int(pair[3:] or 0)
                self._json(200, {"messages": session_messages(sid)})
                return

            if path == "/api/settings":
                from . import licensing

                cfg = state.cfg
                self._json(200, {
                    "provider": cfg.brains.primary.provider,
                    "baseUrl": cfg.brains.primary.base_url,
                    "model": cfg.brains.primary.model,
                    "hasKey": bool(cfg.brains.primary.api_key),
                    "tier": licensing.tier(),
                })
                return

            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"error": "bad JSON"})
                return

            path = self.path.split("?")[0].rstrip("/") or "/"

            if path == "/api/chat":
                text = str(payload.get("text", "")).strip()
                if not text:
                    self._json(400, {"error": "empty message"})
                    return
                result = state.run_turn_async(text)
                self._json(200 if "started" in result else 409, result)
                return

            if path == "/api/confirm":
                answered = state.answer(
                    str(payload.get("confirm_id", "")), bool(payload.get("approved", False))
                )
                self._json(200 if answered else 404, {"answered": answered})
                return

            if path == "/api/resume":
                # Mark XXII - the Record: /resume for the browser console
                from .conversations import session_messages

                target = int(payload.get("id", 0))
                recorded = session_messages(target)
                if not recorded:
                    self._json(404, {"error": f"session #{target} has no messages"})
                    return
                state.agent.reset()
                for entry in recorded:
                    role = entry["role"]
                    if role in ("user", "assistant"):
                        state.agent.messages.append({"role": role, "content": entry["content"]})
                state.push_event(
                    "status",
                    {"text": f"resumed session #{target} - {len(recorded)} messages back in context"},
                )
                self._json(200, {"resumed": target, "messages": len(recorded)})
                return

            if path == "/api/memory/save":
                from .memory import save_note

                note = str(payload.get("note", "")).strip()
                if not note:
                    self._json(400, {"error": "empty note"})
                    return
                note_id = save_note(note)
                self._json(200, {"id": note_id, "status": "saved"})
                return

            if path == "/api/memory/forget":
                from .memory import forget_note

                forget_note(int(payload.get("id", 0)))
                self._json(200, {"status": "deleted"})
                return

            if path == "/api/kanban":
                from .portal import load_board, save_board

                action = str(payload.get("action", ""))
                board = load_board()
                if action == "add":
                    text = str(payload.get("text", "")).strip()
                    if text:
                        next_id = max((t.get("id", 0) for t in board.get("tasks", [])), default=0) + 1
                        board.setdefault("tasks", []).append(
                            {"id": next_id, "column": "todo", "text": text}
                        )
                        save_board(board)
                    self._json(200, board)
                    return
                if action == "cycle":
                    from .portal import cycle_task

                    if cycle_task(board, int(payload.get("id", 0))) is not None:
                        save_board(board)
                    self._json(200, board)
                    return
                self._json(400, {"error": "unknown action"})
                return

            if path == "/api/watch":
                from .watchtower import load_rules, remove_rule, add_rule

                action = str(payload.get("action", ""))
                if action == "add":
                    rule_data = payload.get("rule", {})
                    saved = add_rule(rule_data)
                    self._json(200, {"id": saved["id"], "status": "saved"})
                    return
                if action == "remove":
                    remove_rule(int(payload.get("id", 0)))
                    self._json(200, {"status": "removed"})
                    return
                self._json(200, {"rules": load_rules()})
                return

            if path == "/api/settings":
                from .brain import make_brain_chain
                from .config import BrainConfig, BrainsConfig

                cfg = state.cfg
                # a blank key field means "keep the stored key"
                key = str(payload.get("apiKey", "")).strip()
                if not key:
                    key = cfg.brains.primary.api_key
                primary = BrainConfig(
                    type=str(payload.get("type", "cloud")),
                    provider=str(payload.get("provider", "")),
                    base_url=str(payload.get("baseUrl", "")),
                    model=str(payload.get("model", "")),
                    api_key=key,
                )
                cfg.brains = BrainsConfig(primary=primary, fallback=cfg.brains.fallback)
                cfg.save()
                # the old chain still points at the previous brain - rebuild it
                state.cfg = cfg
                state.agent.chain = make_brain_chain(cfg)
                self._json(200, {"status": "saved"})
                return

            if path == "/api/license/activate":
                from .licensing import install_license

                key = str(payload.get("key", "")).strip()
                ok, message = install_license(key)
                self._json(200 if ok else 400, {"ok": ok, "message": message})
                return

            self._json(404, {"error": "not found"})

        def log_message(self, format: str, *args) -> None:  # silence default logging
            pass

    return DashboardHandler


def _version():
    from . import __version__
    return __version__


def start_server(state: DashboardState, preferred_port: int = DEFAULT_PORT):
    """Bind to 127.0.0.1 on the first free port and START serving in a daemon
    thread. Returns (server, port, thread)."""
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
    port = server.server_address[1]  # real port (preferred_port=0 -> ephemeral)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def run_dashboard(console) -> int:  # pragma: no cover - interactive loop
    from rich.panel import Panel

    cfg = config.Config.load()
    if cfg is None:
        console.print(
            "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] once "
            "and complete the wizard - the dashboard manages that brain."
        )
        return 1
    state = DashboardState(cfg)
    try:
        server, port, thread = start_server(state)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    url = f"http://127.0.0.1:{port}"
    console.print(
        Panel(
            f"[bold cyan]{url}[/]\n\n"
            "The full agent - all tools - with confirmations as APPROVE/DENY\n"
            "in the browser. Bound to 127.0.0.1 only, never the network.\n"
            "Ctrl+C to stop.",
            title="UMBRA - the Dashboard",
            border_style="cyan",
        )
    )
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        pass
    try:
        while thread.is_alive():
            thread.join(timeout=1.0)
    except KeyboardInterrupt:
        console.print("[dim]Dashboard standing down, Sir.[/]")
    finally:
        server.shutdown()
        server.server_close()
    return 0
