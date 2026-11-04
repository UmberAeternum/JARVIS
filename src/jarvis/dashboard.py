"""Mark XVI - the Dashboard: a local web mission control for UMBRA.

A single-page dashboard served at 127.0.0.1 only (never exposed to the
network). Tabbed interface: Chat, Health (the Oracle), Memory (the second
brain), Kanban, Watch rules, and Settings — every subsystem visual and
clickable instead of CLI-only.

All module imports happen lazily inside handler methods (the established
pattern), so the module can be imported without triggering the full stack.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .dashboard_page import PAGE

DEFAULT_PORT = 8773
PORT_ATTEMPTS = 20

SYSTEM_PROMPT = (
    "You are UMBRA, the user's desktop assistant, shown in a web dashboard. "
    "Address the user as Sir. Be brief, factual and helpful."
)


class DashboardState:
    """Holds the brain chain and config for the handler's use."""

    def __init__(self, cfg):
        self.cfg = cfg
        from .brain import make_brain_chain

        self.chain = make_brain_chain(cfg)
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.lock = threading.Lock()


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
            path = self.path.split("?")[0].rstrip("/") or "/"
            if path in ("/", "/index.html"):
                from .dashboard_page import PAGE

                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
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
                with state.lock:
                    state.history.append({"role": "user", "content": text})
                    try:
                        response = state.chain.create_chat(messages=list(state.history))
                        reply = (response.choices[0].message.content or "").strip()
                    except Exception as exc:
                        reply = f"ERROR: {type(exc).__name__}: {exc}"
                    # keep the history consistent even when the turn fails
                    state.history.append({"role": "assistant", "content": reply})
                    if len(state.history) > 41:
                        state.history = [state.history[0]] + state.history[-40:]
                self._json(200, {"reply": reply})
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
                state.chain = make_brain_chain(cfg)
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
            "Bound to 127.0.0.1 only - never exposed to the network. Ctrl+C to stop.",
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
