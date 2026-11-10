"""Phase 13 - hand gestures: opt-in, fully local HUD control.

The camera never leaves the browser: the HUD page (and only the HUD page)
runs hand tracking locally when the vendored tracker files are present, and
sends ONLY normalized landmark coordinates (21 (x, y) pairs) to this module
over the token-gated HUD API. No frames, no images, no storage.

Scope of control (deliberate):
- Gestures drive UMBRA's own HUD only: cursor highlight, select, panel
  navigation, pause. They never touch the OS, never run tools.
- The fist is the KILL SWITCH (phase 11's global halt, third entry point
  after `jarvis stop` and the HUD button).
- HIGH-CONSEQUENCE rule: a gesture can NEVER confirm MONEY / SEND / PUBLISH
  / DELETE / ACCOUNT. gesture_confirm() below is the one seam a future edit
  would have to change, and the control test fails if it ever returns True.

Access: posting landmarks requires the `assist` grant through the policy
spine (access.authorize - no grant checks outside it), the HUD token, an
explicit enable (gestures.enabled, default OFF), and passes a rate limit.
The camera-on indicator lives on the page and is always visible while the
stream runs; an idle timeout auto-stops it.

Landmark model: the MediaPipe Hands 21-point layout (wrist + 4 points per
finger). Classification is pure geometry, fully testable with synthetic
streams - no camera, no vendor bundle, no network in tests.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import config
from . import safety
from .config import config_dir

# MediaPipe Hands 21-landmark indices (normalized coords, y grows downward)
WRIST = 0
THUMB_TIP = 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_PIP, MIDDLE_TIP = 10, 12
RING_PIP, RING_TIP = 14, 16
PINKY_PIP, PINKY_TIP = 18, 20

GESTURE_NAMES = ("point", "pinch", "swipe_left", "swipe_right",
                 "open_palm", "fist", "none")

# The gesture -> HUD action map. There is intentionally NO confirmation verb
# here (no approve/confirm/allow): see gesture_confirm().
ACTION_MAP = {
    "point": "cursor",
    "pinch": "select",
    "swipe_left": "nav_back",
    "swipe_right": "nav_next",
    "open_palm": "pause",
    "fist": "kill",
    "none": None,
}

# HIGH-CONSEQUENCE classes a gesture may NEVER confirm.
CONFIRM_CLASSES = ("MONEY", "SEND", "PUBLISH", "DELETE", "ACCOUNT")

PINCH_BASE = 0.06  # normalized units, scaled by the calibration threshold


def gesture_confirm(action_class: str) -> bool:
    """ALWAYS False. The single seam through which a gesture could ever
    confirm a HIGH-CONSEQUENCE action; the phase-13 control test asserts it
    refuses every class, so adding confirmation here cannot pass CI."""
    return False


# ------------------------------------------------------------- classification


def _extended(tip: int, pip: int, points) -> bool:
    """A finger is extended when its tip sits above its PIP joint (y down)."""
    try:
        return float(points[tip][1]) < float(points[pip][1])
    except (IndexError, TypeError, ValueError):
        return False


def _dist(a, b) -> float:
    return ((float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2) ** 0.5


def classify_landmarks(points, threshold: float = 1.0) -> str:
    """Classify one landmark frame. Geometry only; threshold (calibration)
    scales the pinch distance. Unknown/partial frames classify to "none"."""
    if not isinstance(points, (list, tuple)) or len(points) < 21:
        return "none"
    fingers = (
        _extended(INDEX_TIP, INDEX_PIP, points),
        _extended(MIDDLE_TIP, MIDDLE_PIP, points),
        _extended(RING_TIP, RING_PIP, points),
        _extended(PINKY_TIP, PINKY_PIP, points),
    )
    if not any(fingers):
        return "fist"
    pinch_gap = _dist(points[THUMB_TIP], points[INDEX_TIP])
    if pinch_gap < PINCH_BASE * max(0.1, float(threshold)):
        return "pinch"
    if all(fingers):
        return "open_palm"
    if fingers[0] and not any(fingers[1:]):
        return "point"
    return "none"


class GestureSession:
    """Frame-to-action pipeline: classify + swipe tracking + the action map.

    fist maps to the GLOBAL kill switch (hud.request_stop), not to a page
    effect - the halt must work even though the HUD is display-only.
    """

    def __init__(self, threshold: float = 1.0, swipe_distance: float = 0.22,
                 idle_timeout_s: float = 30.0):
        self.threshold = max(0.1, float(threshold))
        self.swipe_distance = float(swipe_distance)
        self.idle_timeout_s = float(idle_timeout_s)
        self._centers: list[tuple[float, float]] = []
        self.last_seen = 0.0

    def _center(self, points) -> tuple[float, float]:
        return (float(points[WRIST][0]), float(points[WRIST][1]))

    def is_stale(self, now: float | None = None) -> bool:
        """No hand seen within the idle timeout - the page auto-stops."""
        reference = time.monotonic() if now is None else now
        return (reference - self.last_seen) > self.idle_timeout_s if self.last_seen else True

    def observe(self, points, now: float | None = None) -> dict:
        """One frame in, one decision out: {"gesture", "action", "detail"}."""
        self.last_seen = time.monotonic() if now is None else now
        gesture = classify_landmarks(points, self.threshold)
        detail = ""
        # swipes: palm-center travel across the recent window (works for any
        # open-ish posture; classified AFTER the static gesture so a fist
        # can never become a swipe)
        if gesture in ("point", "open_palm", "none"):
            self._centers.append(self._center(points))
            del self._centers[:-8]
            if len(self._centers) >= 3:
                dx = self._centers[-1][0] - self._centers[0][0]
                if dx < -self.swipe_distance:
                    gesture, detail = "swipe_left", f"dx={dx:.2f}"
                elif dx > self.swipe_distance:
                    gesture, detail = "swipe_right", f"dx={dx:.2f}"
        else:
            self._centers.clear()
        action = ACTION_MAP.get(gesture)
        if gesture == "fist" and action == "kill":
            from . import hud as hud_module

            hud_module.request_stop("fist gesture")
            detail = "global halt engaged"
        elif gesture == "open_palm":
            from . import hud as hud_module

            hud_module.set_state("idle")
            detail = "paused by open palm"
        return {"gesture": gesture, "action": action, "detail": detail}


class RateLimiter:
    """Sliding-window limiter for the landmark feed (default 10/s)."""

    def __init__(self, max_per_second: int = 10):
        self.max = max(1, int(max_per_second))
        self._events: list[float] = []

    def allow(self, now: float | None = None) -> bool:
        reference = time.monotonic() if now is None else now
        self._events = [stamp for stamp in self._events if reference - stamp < 1.0]
        if len(self._events) >= self.max:
            return False
        self._events.append(reference)
        return True


# -------------------------------------------------------------------- vendor

# The vendored tracker bundle (browser-side MediaPipe Hands, Apache-2.0).
# Files are fetched ONCE on the user's explicit command through the
# SSRF-guarded fetcher and served locally afterwards - never from a CDN at
# runtime. Without the bundle the HUD shows "tracker not installed" and
# gestures stay off; nothing degrades.

HANDS_VERSION = "0.4.1675469240"
HANDS_BASE = f"https://cdn.jsdelivr.net/npm/@mediapipe/hands@{HANDS_VERSION}"
HANDS_FILES = (
    "hands.js",
    "hands_solution_packed_assets_loader.js",
    "hands_solution_simd_wasm_bin.js",
    "hands_solution_simd_wasm_bin.wasm",
    "hands.binarypb",
)
MAX_VENDOR_BYTES = 40_000_000


def vendor_dir() -> Path:
    return config_dir() / "vendor" / "hands"


def vendor_status() -> dict:
    """Which bundle files are present locally (never fetches)."""
    root = vendor_dir()
    return {
        "dir": str(root),
        "version": HANDS_VERSION,
        "present": {name: (root / name).is_file() for name in HANDS_FILES},
        "complete": all((root / name).is_file() for name in HANDS_FILES),
    }


def vendor_download(on_status) -> tuple[bool, str]:
    """Fetch the bundle once, guarded (scheme/host/IP rules, size caps)."""
    root = vendor_dir()
    root.mkdir(parents=True, exist_ok=True)
    for name in HANDS_FILES:
        target = root / name
        if target.is_file():
            continue
        on_status(f"fetching {name}")
        data, reason = safety.guarded_fetch_bytes(
            f"{HANDS_BASE}/{name}", MAX_VENDOR_BYTES, timeout=120.0
        )
        if data is None:
            return False, f"{name}: {reason}"
        target.write_bytes(data)
    return True, ""


# -------------------------------------------------------------------- config


def gestures_config() -> config.GesturesConfig:
    return config.Config.load().gestures if config.Config.load() else config.GesturesConfig()


def session_from_config() -> GestureSession:
    cfg = config.Config.load() or config.Config()
    return GestureSession(
        threshold=cfg.gestures.threshold,
        idle_timeout_s=cfg.gestures.idle_timeout_s,
    )


# The HUD server's shared session + feed limiter (module singletons so swipe
# history survives across requests; the CLI calibrate command updates
# GESTURE_SESSION.threshold in place).
GESTURE_SESSION = GestureSession()
GESTURE_RATE = RateLimiter(max_per_second=10)
