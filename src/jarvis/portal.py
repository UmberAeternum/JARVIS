"""Mark VII - the Portal: a WebXR window into JARVIS, for headsets and phones.

Architecture:
- A token-gated HTTP server bound to the LAN (0.0.0.0): a headset or phone is
  a separate device and cannot reach 127.0.0.1, so this is the one component
  that deliberately exposes a network listener. Exposure is bounded: a random
  per-session token is required on every request, the URL (with token) is
  printed to the console for the user to open in the headset browser, and the
  server is stopped with Ctrl+C.
- The page is a three.js WebXR room: a chat panel, a kanban wall (cards cycle
  TODO -> DOING -> DONE on select), and a desk for the user's own GLB models
  (drop them into the config directory's models/ folder - BYO assets, same
  philosophy as BYO key and BYO avatar).
- Text entry in-headset uses the DOM Overlay (supported by Quest Browser);
  the same page also works as a plain 2D fallback in any desktop browser.
- Chat runs through the configured brain chain (primary + fallback),
  conversation-only, exactly like the avatar.

Verification reality: HTTP contract and storage are tested here; the XR
rendering itself can only be judged in a headset or WebXR-capable phone.
"""

from __future__ import annotations

import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config
from .brain import BrainChain, make_brain_chain
from .portal_page import PAGE_XR

DEFAULT_PORT = 8771
SYSTEM_PROMPT = (
    "You are J.A.R.V.I.S., present in the user's room through their headset. "
    "Address the user as Sir. Replies appear on a floating panel and are short, "
    "factual and conversational: no markdown, no lists."
)

KANBAN_DEFAULT = {"tasks": [{"id": 1, "column": "todo", "text": "Welcome to the board, Sir"}]}
COLUMNS = ("todo", "doing", "done")


def lan_address() -> str:
    """Best-effort LAN address of this machine (for the printed URL)."""
    try:
        hostname = socket.gethostname()
        address = socket.gethostbyname(hostname)
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    return "127.0.0.1"


def _board_path() -> Path:
    return config.config_dir() / "board.json"


def _models_dir() -> Path:
    return config.config_dir() / "models"


def load_board() -> dict:
    path = _board_path()
    if not path.is_file():
        return json.loads(json.dumps(KANBAN_DEFAULT))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return data
    except (OSError, ValueError):
        pass
    return json.loads(json.dumps(KANBAN_DEFAULT))


def save_board(board: dict) -> None:
    _board_path().parent.mkdir(parents=True, exist_ok=True)
    _board_path().write_text(json.dumps(board, indent=2), encoding="utf-8")


def cycle_task(board: dict, task_id: int) -> dict | None:
    for task in board.get("tasks", []):
        if task.get("id") == task_id:
            current = task.get("column", "todo")
            try:
                index = COLUMNS.index(current)
            except ValueError:
                index = 0
            task["column"] = COLUMNS[(index + 1) % len(COLUMNS)]
            return task
    return None


class PortalState:
    """Brain chain + board, shared by the HTTP handler."""

    def __init__(self, chain: BrainChain, token: str):
        self.chain = chain
        self.token = token
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.lock = threading.Lock()

    def authorized(self, token: str | None) -> bool:
        return bool(token) and secrets.compare_digest(token, self.token)

    def chat(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"reply": "", "error": "empty message"}
        with self.lock:
            self.history.append({"role": "user", "content": text})
            try:
                response = self.chain.create_chat(messages=list(self.history))
                reply = (response.choices[0].message.content or "").strip()
                self.history.append({"role": "assistant", "content": reply})
            except Exception as exc:
                reply = f"ERROR: {type(exc).__name__}: {exc}"
            if len(self.history) > 41:
                self.history = [self.history[0]] + self.history[-40:]
        return {"reply": reply}


def make_handler(state: PortalState) -> type:
    class PortalHandler(BaseHTTPRequestHandler):
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
            query = self.path.split("?")
            if len(query) == 2:
                for pair in query[1].split("&"):
                    if pair.startswith("t="):
                        return pair[2:]
            return None

        def _authorized(self) -> bool:
            return state.authorized(self._token())

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            path, _, query = self.path.partition("?")
            path = path.rstrip("/") or "/"
            if path == "/" and state.authorized(self._token()):
                self._send(200, PAGE_XR.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/" :
                self._send(403, b"portal requires the session token", "text/plain")
                return
            if not state.authorized(self._token()):
                self._send(403, b"forbidden - missing session token", "text/plain")
                return
            if path == "/api/board":
                self._send(200, json.dumps(load_board()).encode("utf-8"), "application/json")
                return
            if path == "/api/health":
                self._send(200, json.dumps({"ok": True}).encode("utf-8"), "application/json")
                return
            if path == "/api/models":
                models_dir = _models_dir()
                names = sorted(p.name for p in models_dir.glob("*.glb")) if models_dir.is_dir() else []
                self._send(200, json.dumps({"models": names}).encode("utf-8"), "application/json")
                return
            if path.startswith("/model/"):
                name = Path(path[len("/model/"):]).name  # no traversal: basename only
                candidate = _models_dir() / name
                if candidate.is_file():
                    self._send(200, candidate.read_bytes(), "model/gltf-binary")
                else:
                    self._send(404, b"no such model - drop .glb files into the models folder", "text/plain")
                return
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            path = self.path.split("?")[0]
            if not state.authorized(self._token()):
                self._send(403, b"forbidden - missing session token", "text/plain")
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._send(400, json.dumps({"error": "bad JSON"}).encode("utf-8"), "application/json")
                return

            if path == "/api/chat":
                result = state.chat(str(payload.get("text", "")))
                self._send(200, json.dumps(result).encode("utf-8"), "application/json")
                return
            if path == "/api/board":
                action = str(payload.get("action", ""))
                board = load_board()
                if action == "cycle":
                    moved = cycle_task(board, int(payload.get("id", 0)))
                    if moved is None:
                        self._send(404, json.dumps({"error": "no such task"}).encode("utf-8"), "application/json")
                        return
                    save_board(board)
                elif action == "add":
                    text = str(payload.get("text", "")).strip()
                    if not text:
                        self._send(400, json.dumps({"error": "empty task"}).encode("utf-8"), "application/json")
                        return
                    next_id = max((t.get("id", 0) for t in board.get("tasks", [])), default=0) + 1
                    board.setdefault("tasks", []).append({"id": next_id, "column": "todo", "text": text})
                    save_board(board)
                else:
                    self._send(400, json.dumps({"error": "unknown action"}).encode("utf-8"), "application/json")
                    return
                self._send(200, json.dumps(board).encode("utf-8"), "application/json")
                return
            self._send(404, b"not found", "text/plain")

        def log_message(self, format: str, *args) -> None:  # silence default logging
            pass

    return PortalHandler


def start_server(
    state: PortalState, preferred_port: int = DEFAULT_PORT
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


def run_portal(console) -> int:  # pragma: no cover - interactive loop
    from rich.panel import Panel

    cfg = config.Config.load()
    if cfg is None:
        console.print(
            "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] once "
            "and complete the wizard - the portal speaks through that brain."
        )
        return 1
    token = secrets.token_urlsafe(6)
    state = PortalState(make_brain_chain(cfg), token)
    try:
        server, port, thread = start_server(state)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    address = lan_address()
    url = f"http://{address}:{port}/?t={token}"
    console.print(
        Panel(
            f"[bold cyan]{url}[/]\n\n"
            "Open this URL in the browser of your headset (or phone for AR, or a "
            "desktop browser for the 2D fallback).\n"
            f"brain: {cfg.brains.primary.provider} ({cfg.brains.primary.model})\n"
            f"models: drop .glb files into {_models_dir()}\n\n"
            "[yellow]Security:[/] the portal is now reachable from your local "
            "network and gated only by this session token. It stops with Ctrl+C.",
            title="J.A.R.V.I.S. - the Portal",
            border_style="cyan",
        )
    )
    try:
        while thread.is_alive():
            thread.join(timeout=1.0)
    except KeyboardInterrupt:
        console.print("[dim]Portal standing down, Sir.[/]")
    finally:
        server.shutdown()
        server.server_close()
    return 0
