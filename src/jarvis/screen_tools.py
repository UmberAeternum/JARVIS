"""Screen control - the model's hands on the display.

Deliberately the most conservative tools in the registry:
- Every single action calls the confirmation gate at execution time. Nothing
  clicks, types, presses or scrolls without the human approving that exact
  action.
- Coordinates are validated and bounded before the gate is even asked.
- pyautogui's failsafe stays armed: slamming the mouse into a screen corner
  aborts automation physically.
- Disabled unless explicitly enabled: tools.default_registry(
  allow_screen_control=True), wired from the vision.screen_control config
  flag (default False).
"""

from __future__ import annotations

MIN_COORD = 0
MAX_COORD = 20_000


def _check_coord(x, y) -> tuple[int, int]:
    try:
        xi, yi = int(x), int(y)
    except (TypeError, ValueError):
        raise ValueError("coordinates must be integers") from None
    if not (MIN_COORD <= xi <= MAX_COORD and MIN_COORD <= yi <= MAX_COORD):
        raise ValueError(f"coordinates out of range ({MIN_COORD}-{MAX_COORD})")
    return xi, yi


def _pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = True  # corner-slam abort stays armed, always
    return pyautogui


def register_screen_tools(registry) -> None:
    def screen_click(x: int, y: int, button: str = "left") -> str:
        xi, yi = _check_coord(x, y)
        if button not in ("left", "right", "middle"):
            return "ERROR: button must be left, right or middle"
        if not registry.confirm(f"Move the mouse and {button}-click at ({xi}, {yi})?"):
            return "BLOCKED: the user declined this click."
        _pyautogui().click(x=xi, y=yi, button=button)
        return f"Clicked {button} at ({xi}, {yi}). Use /look to verify the result."

    def screen_type(text: str) -> str:
        if not text:
            return "ERROR: empty text"
        if not registry.confirm(
            f"Type {len(text)} characters into the currently focused window?"
        ):
            return "BLOCKED: the user declined typing."
        _pyautogui().typewrite(text, interval=0.01)  # ASCII only
        return (
            f"Typed {len(text)} characters. Note: typing is ASCII-only; "
            "non-ASCII text needs the clipboard."
        )

    def screen_press(key: str) -> str:
        key = (key or "").strip()
        if not key:
            return "ERROR: empty key name"
        if not registry.confirm(f"Press key '{key}'?"):
            return "BLOCKED: the user declined this key press."
        _pyautogui().press(key)
        return f"Pressed {key}."

    def screen_scroll(amount: int) -> str:
        try:
            clicks = int(amount)
        except (TypeError, ValueError):
            return "ERROR: amount must be an integer"
        if clicks == 0:
            return "ERROR: amount must be non-zero"
        if not registry.confirm(f"Scroll {clicks} click(s) (positive = up)?"):
            return "BLOCKED: the user declined scrolling."
        _pyautogui().scroll(clicks)
        return f"Scrolled {clicks} click(s)."

    registry.register(
        "screen_click",
        "Move the mouse and click at screen coordinates (x, y). Use the "
        "screenshot/vision view to pick coordinates. Requires user confirmation.",
        {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "middle"]},
            },
            "required": ["x", "y"],
        },
        screen_click,
    )
    registry.register(
        "screen_type",
        "Type text into the currently focused window (ASCII only). Requires "
        "user confirmation.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        screen_type,
    )
    registry.register(
        "screen_press",
        "Press a keyboard key by name (e.g. 'enter', 'tab', 'esc'). Requires "
        "user confirmation.",
        {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        screen_press,
    )
    registry.register(
        "screen_scroll",
        "Scroll the mouse wheel; positive is up. Requires user confirmation.",
        {
            "type": "object",
            "properties": {"amount": {"type": "integer"}},
            "required": ["amount"],
        },
        screen_scroll,
    )
