"""Mark XXVIII - ambient presence: proactive, rate-limited, never spammy.

Pure logic, fully testable: the sentinel daemon supplies live data each
cycle and announces whatever this module returns.

Rules baked in here:
- one concise nudge per evaluation (pick()), per-signal rate-limited
- quiet hours respected (windows may cross midnight)
- everything is opt-in: the master switch lives in config (ambient.nudges,
  default False) and per-signal toggles gate each candidate
- nudges never repeat inside the rate-limit window (fired map, per signal)
"""

from __future__ import annotations

from datetime import datetime, timedelta

_HEALTH_BANDS = ("HIGH", "ELEVATED", "WATCH")


def parse_clock(value: str) -> tuple[int, int] | None:
    """'HH:MM' -> (hour, minute); None when unparseable."""
    try:
        parts = value.strip().split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (ValueError, IndexError, AttributeError):
        pass
    return None


def in_quiet_hours(now: datetime, quiet_start: str, quiet_end: str) -> bool:
    """True when `now` sits inside [quiet_start, quiet_end). The window may
    cross midnight (23:00 -> 07:00). Unparseable bounds mean never quiet."""
    start = parse_clock(quiet_start)
    end = parse_clock(quiet_end)
    if start is None or end is None:
        return False
    minutes = now.hour * 60 + now.minute
    start_m, end_m = start[0] * 60 + start[1], end[0] * 60 + end[1]
    if start_m == end_m:
        return False
    if start_m < end_m:  # same-day window
        return start_m <= minutes < end_m
    return minutes >= start_m or minutes < end_m  # crosses midnight


def nudge_ready(last_sent: float, now: float, rate_limit_min: int) -> bool:
    """Rate gate: at most one nudge per rate_limit_min minutes (globally)."""
    return (now - last_sent) >= rate_limit_min * 60


def candidates(
    vitals: dict,
    due_reminders: int,
    health_report: str,
    honorific: str = "Sir",
    battery: bool = True,
    health: bool = True,
    reminders: bool = True,
) -> list[tuple[str, str]]:
    """(signal_key, text) pairs for every actionable signal right now.
    Per-signal toggles gate each family independently."""
    out: list[tuple[str, str]] = []
    if battery:
        level = vitals.get("battery")
        if isinstance(level, (int, float)) and 0 <= level < 25:
            out.append((
                "battery",
                f"{honorific}, your battery is at {int(level)}% — shall I plug in?",
            ))
    if reminders and due_reminders > 0:
        out.append((
            "reminders",
            f"{honorific}, {due_reminders} reminder(s) are due.",
        ))
    if health and health_report:
        first_line = health_report.splitlines()[0] if health_report else ""
        band = next((b for b in _HEALTH_BANDS if f"HEALTH SIGNAL: {b}" in first_line), None)
        if band:
            out.append((
                "health",
                f"{honorific}, your health signals have moved to {band}. "
                "You may want to review the Oracle.",
            ))
    return out


def pick(
    candidates_: list[tuple[str, str]],
    fired: dict[str, float],
    now: float,
    rate_limit_min: int,
    quiet: bool,
) -> tuple[str, str] | None:
    """One concise nudge per evaluation: the first (signal_key, text) whose
    signal has not fired inside the rate-limit window. None when quiet or
    exhausted - the caller records the returned key's fire time."""
    if quiet:
        return None
    for key, text in candidates_:
        if (now - fired.get(key, 0.0)) >= rate_limit_min * 60:
            return key, text
    return None
