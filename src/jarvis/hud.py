"""Phase 11 - the Orb HUD: a token-gated, DISPLAY-ONLY web surface.

`jarvis hud serve` starts the particle-orb HUD at 127.0.0.1 only. It shows
UMBRA's live state (idle/listening/thinking/working/speaking/alert), a status
ring (CPU/RAM/battery/tier/grants), a live action log, devices, captions, and
the avatar info panels (BRAIN: route/model - BODY: state - CHAIN: recent
steps). It renders; it never acts: there are no tool endpoints here and no
chat - the dashboard and the Bridge remain the interactive surfaces.

Auth: every request carries the HUD token (X-Jarvis-Token header or ?t=).
The token lives in <config>/hud-token (0600 on POSIX) - the same pattern as
the local API. The page itself is static (no data) and loads without a
token; every /api endpoint requires one, so a stray local process or a
webpage cannot read the HUD.

The kill switch lives here too (the HIGH-CONSEQUENCE rule needs one global
halt): `jarvis stop`, the HUD's KILL button, and (phase 13) the fist gesture
all call request_stop(). Every surface wired with should_stop checks it
between tool calls and stops. Stopping a streaming model call mid-generation
is not possible - the halt lands between tool iterations, which is where all
side effects are.

State feed: other surfaces push into the module-level HUD store
(observe_status / set_state / set_caption) - the dashboard forwards its
status stream, so the orb moves when the agent works. No surface in this
module grants access, runs tools, or answers chat.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config
from .hud_page import PAGE

DEFAULT_PORT = 8776
PORT_ATTEMPTS = 20
MAX_EVENTS = 600

# The six agent states and their HUD colors (the spec's mapping, one
# authoritative copy server-side; the page mirrors it for instant paint).
STATE_COLORS: dict[str, str] = {
    "idle": "#14b8a6",       # teal
    "listening": "#3b82f6",  # blue
    "thinking": "#e5e7eb",   # white (pulsing on the page)
    "working": "#22c55e",    # green
    "speaking": "#f59e0b",   # amber
    "alert": "#ef4444",      # red
}

THEMES = ("minimal", "hud", "scanline", "hologram")  # hologram = legacy alias of hud


def state_color(state: str) -> str:
    """Hex color for an agent state; unknown states fall back to idle."""
    return STATE_COLORS.get(state, STATE_COLORS["idle"])


# ------------------------------------------------------------------ token


def token_path() -> Path:
    return config.config_dir() / "hud-token"


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


# -------------------------------------------------------------- kill switch

# The global halt flag (HIGH-CONSEQUENCE rule). Latched on purpose: it takes
# an explicit clear (`jarvis stop --clear`) to run again after a kill.
_KILL = threading.Event()


def request_stop(source: str = "kill switch") -> None:
    """Halt all wired actions ASAP. Latched until clear_stop()."""
    _KILL.set()
    HUD.push_action(f"KILL SWITCH engaged ({source}) - halting all actions")
    HUD.set_state("alert")


def clear_stop() -> None:
    """Rearm after a kill (deliberate: `jarvis stop --clear`)."""
    _KILL.clear()


def should_stop() -> bool:
    """The one-line check every action loop calls between steps."""
    return _KILL.is_set()


# ------------------------------------------------------------------- state


class HudState:
    """Thread-safe display state: what the orb, panels and log show."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._state = "idle"
        self._actions: list[dict] = []
        self._captions = ""
        self._devices: list[dict] = []
        self._route: dict = {}
        self._chain: list[str] = []

    # reads (never raise on empty - the HUD must render before any feed)

    @property
    def state(self) -> str:
        with self._cond:
            return self._state

    @property
    def captions(self) -> str:
        with self._cond:
            return self._captions

    @property
    def devices(self) -> list[dict]:
        with self._cond:
            return list(self._devices)

    @property
    def route(self) -> dict:
        with self._cond:
            return dict(self._route)

    @property
    def chain(self) -> list[str]:
        with self._cond:
            return list(self._chain)

    def recent_actions(self, limit: int = 30) -> list[dict]:
        with self._cond:
            return list(self._actions[-limit:])

    # writes

    def set_state(self, state: str) -> None:
        with self._cond:
            self._state = state if state in STATE_COLORS else "idle"

    def push_action(self, text: str) -> int:
        """One line in the live action log; returns its event id."""
        with self._cond:
            event = {
                "id": len(self._actions) + 1,
                "ts": time.strftime("%H:%M:%S"),
                "text": str(text)[:300],
            }
            self._actions.append(event)
            if len(self._actions) > MAX_EVENTS:
                del self._actions[: len(self._actions) - MAX_EVENTS]
            self._cond.notify_all()
            return event["id"]

    def set_caption(self, text: str) -> None:
        with self._cond:
            self._captions = str(text)[:400]

    def observe_device(self, device: dict) -> None:
        """Upsert one device (name/tier/last_seen) for the devices panel."""
        with self._cond:
            name = str(device.get("name", "?"))
            for known in self._devices:
                if known.get("name") == name:
                    known.update(device)
                    return
            self._devices.append(dict(device))

    def observe_route(self, why: str, model: str = "", provider: str = "") -> None:
        with self._cond:
            self._route = {"why": str(why)[:200], "model": model, "provider": provider}

    def observe_chain(self, step: str) -> None:
        """One recent agent step (BRAIN/BODY/CHAIN avatar panel)."""
        with self._cond:
            self._chain.append(str(step)[:160])
            del self._chain[:-10]

    # long-poll

    def events_since(self, since: int) -> list[dict]:
        with self._cond:
            return [event for event in self._actions if event["id"] > since]

    def wait_for_events(self, since: int, timeout: float) -> list[dict]:
        with self._cond:
            if not any(event["id"] > since for event in self._actions):
                self._cond.wait(timeout=timeout)
            return [event for event in self._actions if event["id"] > since]


# The process-wide display store. The dashboard forwards its status stream
# here; the CLI and (later) voice push captions. Display data only.
HUD = HudState()


def observe_status(status: str) -> None:
    """Feed one status line into the orb's action log + chain panel."""
    HUD.push_action(status)
    HUD.observe_chain(status)


def set_state(state: str) -> None:
    HUD.set_state(state)


# ---------------------------------------------------------------- handler


def make_handler(store: HudState, cfg: config.Config) -> type:
    class HudHandler(BaseHTTPRequestHandler):
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
            path, _, query = self.path.partition("?")
            path = path.rstrip("/") or "/"
            if path in ("/", "/index.html"):
                # The page shell is static - no data without the token.
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if not self._authorized():
                self._json(403, {"error": "forbidden - missing or invalid HUD token"})
                return
            if path == "/api/state":
                self._json(200, self._full_state())
                return
            if path == "/api/events":
                since = 0
                for pair in query.split("&"):
                    if pair.startswith("since="):
                        try:
                            since = int(pair[6:] or 0)
                        except ValueError:
                            since = 0  # malformed since polls from the start
                events = store.wait_for_events(since, timeout=10.0)
                last = events[-1]["id"] if events else since
                self._json(200, {"events": events, "last": last})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            # Drain the body BEFORE any early 403 (keep-alive parity with api.py).
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            if not self._authorized():
                self._json(403, {"error": "forbidden - missing or invalid HUD token"})
                return
            path = self.path.split("?")[0].rstrip("/") or "/"
            if path == "/api/stop":
                # The one POST this surface accepts: the global halt. The
                # button is instant by design - the kill switch must not
                # itself stand behind a confirmation.
                try:
                    json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    pass  # body ignored; the flag does the work
                request_stop("HUD button")
                self._json(200, {"stopped": True, "should_stop": should_stop()})
                return
            self._json(404, {"error": "not found"})

        def _full_state(self) -> dict:
            from . import __version__, licensing, system_prompt
            from . import access as access_module

            try:
                from .watchtower import read_vitals

                vitals = read_vitals()
            except Exception:
                vitals = {}
            route = store.route
            return {
                "version": __version__,
                "state": store.state,
                "color": state_color(store.state),
                "hud": {
                    "theme": cfg.hud.theme,
                    "sound": cfg.hud.sound,
                    "typed": cfg.hud.typed,
                    "boot": cfg.hud.boot,
                    "reduced_motion": getattr(cfg.hud, "reduced_motion", False),
                },
                "honorific": system_prompt.honorific(),
                "vitals": vitals,
                "tier": licensing.tier(),
                "grants": access_module.tier_snapshot(),
                "brain": {
                    "provider": cfg.brains.primary.provider,
                    "model": cfg.brains.primary.model,
                    "why": route.get("why", ""),
                },
                "chain": store.chain,
                "captions": store.captions,
                "devices": store.devices,
                "actions": store.recent_actions(30),
                "stop_requested": should_stop(),
            }

        def log_message(self, format: str, *args) -> None:  # silence: no token leakage
            pass

    return HudHandler


# ----------------------------------------------------------------- server


def start_server(
    store: HudState, cfg: config.Config, preferred_port: int = DEFAULT_PORT
) -> tuple[ThreadingHTTPServer, int, threading.Thread]:
    """Bind to 127.0.0.1 on the first free port and START serving in a daemon
    thread. Loopback is a hard property of the HUD - phones get it through
    the Bridge (phase 18), never by exposing this server."""
    last_error: Exception | None = None
    for offset in range(PORT_ATTEMPTS):
        port = preferred_port + offset
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, cfg))
            break
        except OSError as exc:
            last_error = exc
    else:
        raise RuntimeError(f"no free local port in range: {last_error}")
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def run_hud(console) -> int:  # pragma: no cover - interactive loop
    from rich.panel import Panel

    cfg = config.Config.load() or config.Config()
    token = ensure_token()
    try:
        server, port, thread = start_server(HUD, cfg)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    url = f"http://127.0.0.1:{port}/?t={token}"
    console.print(
        Panel(
            f"[bold cyan]http://127.0.0.1:{port}/?t=...[/]\n\n"
            "The Orb HUD: state, status ring, action log, devices, captions,\n"
            "and the BRAIN/BODY/CHAIN avatar panels. Display only - no chat,\n"
            "no tools, no approvals. KILL button + [bold]jarvis stop[/] halt actions.\n"
            f"token file: {token_path()}  (rotate: [bold]jarvis hud token rotate[/])\n\n"
            "[yellow]Loopback only.[/] Ctrl+C stops.",
            title="UMBRA - the Orb HUD",
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
        console.print("[dim]HUD standing down, Sir.[/]")
    finally:
        server.shutdown()
        server.server_close()
    return 0
