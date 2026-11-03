"""Mark VI - the Avatar: a local web face for the assistant.

Architecture:
- A small HTTP server bound to 127.0.0.1 only (never exposed to the network).
- Serves one self-contained page: a procedural HUD face (works everywhere,
  zero assets) with an optional BYO-model 3D mode - drop `avatar.vrm` into
  the config directory and the page loads it through three-vrm. No licensed
  character ships with this software; you bring your own model, exactly like
  you bring your own key.
- Speech happens in the browser (speechSynthesis) so lip-sync reacts to the
  real utterance events; the server never plays audio.
- Chat posts to /api/chat, which runs the configured brain chain (primary +
  fallback). Conversation-only by design: the desktop CLI remains the tool
  surface, because tool confirmations need the human at that terminal.

The brain is resolved lazily per request; nothing heavy happens at import.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from . import config
from .brain import BrainChain, make_brain_chain
from .avatar_page import PAGE

SYSTEM_PROMPT = (
    "You are J.A.R.V.I.S., speaking aloud through the user's avatar. Address "
    "the user as Sir. Replies are rendered as speech, so keep them short and "
    "conversational: no markdown, no lists, no code blocks. Report failures "
    "plainly."
)

DEFAULT_PORT = 8770
PORT_ATTEMPTS = 20


class AvatarState:
    """Everything the HTTP handler needs: the brain chain and the dialogue."""

    def __init__(self, chain: BrainChain):
        self.chain = chain
        self.history: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self.lock = threading.Lock()

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
            except Exception as exc:  # reported honestly, never thrown at the page
                reply = f"ERROR: {type(exc).__name__}: {exc}"
            # keep the dialogue bounded: system + last 20 turns
            if len(self.history) > 41:
                self.history = [self.history[0]] + self.history[-40:]
        return {"reply": reply}


def _vrm_path() -> Path:
    return config.config_dir() / "avatar.vrm"


def make_handler(state: AvatarState) -> type:
    class AvatarHandler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/avatar.vrm":
                model = _vrm_path()
                if model.is_file():
                    self._send(200, model.read_bytes(), "application/octet-stream")
                else:
                    self._send(404, b"no avatar.vrm in the config directory", "text/plain")
            elif path == "/api/health":
                body = json.dumps({"ok": True}).encode("utf-8")
                self._send(200, body, "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            path = self.path.split("?")[0]
            if path != "/api/chat":
                self._send(404, b"not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
                text = str(payload.get("text", ""))
            except (ValueError, UnicodeDecodeError):
                self._send(400, json.dumps({"reply": "", "error": "bad JSON"}).encode(), "application/json")
                return
            result = state.chat(text)
            self._send(200, json.dumps(result).encode("utf-8"), "application/json")

        def log_message(self, format: str, *args) -> None:  # silence default logging
            pass

    return AvatarHandler


def start_server(
    state: AvatarState, preferred_port: int = DEFAULT_PORT
) -> tuple[ThreadingHTTPServer, int, threading.Thread]:
    """Bind to 127.0.0.1 on the first free port and START serving in a daemon
    thread. Returns (server, port, thread) - shutdown() is safe after this."""
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
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def run_avatar(console) -> int:  # pragma: no cover - interactive loop
    from rich.panel import Panel

    cfg = config.Config.load()
    if cfg is None:
        console.print(
            "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] once "
            "and complete the wizard - the avatar speaks through that brain."
        )
        return 1
    state = AvatarState(make_brain_chain(cfg))
    try:
        server, port, thread = start_server(state)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    has_vrm = _vrm_path().is_file()
    url = f"http://127.0.0.1:{port}"
    console.print(
        Panel(
            f"[bold cyan]{url}[/]\n\n"
            f"brain: {cfg.brains.primary.provider} ({cfg.brains.primary.model})\n"
            f"3D model: {'avatar.vrm found' if has_vrm else 'not found - procedural HUD face in use'}\n"
            "Bound to 127.0.0.1 only. Ctrl+C to stand down.",
            title="J.A.R.V.I.S. - the Avatar",
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
        console.print("[dim]Avatar standing down, Sir.[/]")
    finally:
        server.shutdown()
        server.server_close()
    return 0
