"""Mark V - the Oracle: health signals from heart-rate data, honestly framed.

What this is:
- A local store for heart-rate-variability (HRV, ms) and resting-HR samples
  (SQLite in the user config directory - data never leaves the machine).
- CSV import for wearable exports (Garmin Connect, Oura, or any file with a
  timestamp column and a value column).
- A rolling 30-day personal baseline with z-score screening: nightly HRV
  suppression and resting-HR elevation are known statistical precursors of
  respiratory illness by roughly one to two days.

What this is NOT:
- A medical device or a diagnosis. Risk levels are screening heuristics
  against your own baseline, reported with their sigma values so the model
  (and the human) can judge them. The tool output states this explicitly.
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

KIND_HRV = "hrv_ms"
KIND_RHR = "resting_hr"
KINDS = (KIND_HRV, KIND_RHR)

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS health_samples ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " kind TEXT NOT NULL,"
    " value REAL NOT NULL,"
    " sampled_at TEXT NOT NULL"
    ")"
)

BASELINE_DAYS = 30
RECENT_HOURS = 36
MIN_BASELINE_SAMPLES = 7

DISCLAIMER = (
    "Screening heuristic against your own baseline - not a medical diagnosis."
)

# z-score bands (|z| for HRV is inverted: suppression is the risk direction)
def risk_band(z: float, inverted: bool) -> str:
    magnitude = -z if inverted else z
    if magnitude >= 2.5:
        return "HIGH"
    if magnitude >= 1.5:
        return "ELEVATED"
    if magnitude >= 1.0:
        return "WATCH"
    return "BASELINE"


def _db_path() -> Path:
    # resolved through the config module so tests can redirect the directory
    return config.config_dir() / "health.db"


def _connect() -> sqlite3.Connection:
    _db_path().parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(_db_path()))
    connection.executescript(SCHEMA)
    return connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_sample(kind: str, value: float, sampled_at: str | None = None) -> int:
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    connection = _connect()
    try:
        cursor = connection.execute(
            "INSERT INTO health_samples (kind, value, sampled_at) VALUES (?, ?, ?)",
            (kind, float(value), sampled_at or _utc_now()),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def samples_since(kind: str, since: str) -> list[tuple[float, str]]:
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT value, sampled_at FROM health_samples "
            "WHERE kind = ? AND sampled_at >= ? ORDER BY sampled_at",
            (kind, since),
        ).fetchall()
    finally:
        connection.close()
    return [(float(r[0]), r[1]) for r in rows]


def baseline(kind: str, days: int = BASELINE_DAYS) -> tuple[float, float, int]:
    """(mean, std, n) over the trailing window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    values = [v for v, _stamp in samples_since(kind, cutoff)]
    if not values:
        return 0.0, 0.0, 0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, variance ** 0.5, len(values)


def import_csv(path: str, kind: str, workspace: Path | None = None) -> int:
    """Import a wearable CSV export (timestamp column + value column).

    Accepts a header row naming the columns (anything containing 'time',
    'date' or 'timestamp' for the timestamp; 'value', 'hrv' or 'hr' for the
    reading) or a headerless two-column file. Returns the number of rows
    imported. Raises ValueError with a readable reason on malformed input.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    resolved = Path(path).expanduser()
    if workspace is not None and not resolved.is_absolute():
        resolved = Path(workspace) / resolved
    if not resolved.is_file():
        raise ValueError(f"file not found: {resolved}")
    imported = 0
    with open(resolved, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError("the file is empty")
    first = [cell.strip().lower() for cell in rows[0]]
    has_header = any(
        marker in cell for cell in first for marker in ("time", "date", "value", "hrv", "hr")
    )
    if has_header:
        ts_idx = next(
            (i for i, cell in enumerate(first) if any(m in cell for m in ("time", "date"))),
            None,
        )
        val_idx = next(
            (i for i, cell in enumerate(first) if any(m in cell for m in ("value", "hrv", "hr"))),
            None,
        )
        if ts_idx is None or val_idx is None:
            raise ValueError("could not identify timestamp and value columns in the header")
        data_rows = rows[1:]
    else:
        if len(rows[0]) < 2:
            raise ValueError("headerless CSV must have at least two columns: timestamp, value")
        ts_idx, val_idx = 0, 1
        data_rows = rows

    for row in data_rows:
        if len(row) <= max(ts_idx, val_idx):
            continue
        value = float(row[val_idx].strip())
        stamp = row[ts_idx].strip()
        # normalise to ISO-8601 with offset where possible; keep as-is otherwise
        try:
            stamp = datetime.fromisoformat(stamp).astimezone(timezone.utc).isoformat(
                timespec="seconds"
            )
        except ValueError:
            pass
        add_sample(kind, value, stamp)
        imported += 1
    return imported


def risk_assessment() -> str:
    """The Oracle's report: per-signal z-scores, bands and honest framing."""
    lines: list[str] = []
    findings: list[tuple[str, float, str]] = []
    insufficient: list[str] = []

    for kind, label, inverted in (
        (KIND_HRV, "HRV", True),
        (KIND_RHR, "Resting HR", False),
    ):
        mean, std, n = baseline(kind)
        recent_cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=RECENT_HOURS)
        ).isoformat(timespec="seconds")
        recent = samples_since(kind, recent_cutoff)
        if n < MIN_BASELINE_SAMPLES or not recent:
            insufficient.append(f"{label} ({n} baseline samples, {len(recent)} recent)")
            continue
        recent_value = sum(v for v, _ in recent) / len(recent)
        z = (recent_value - mean) / std if std > 0 else 0.0
        band = risk_band(z, inverted)
        direction = "suppressed" if inverted and z < 0 else ("elevated" if z > 0 else "normal")
        lines.append(
            f"{label}: recent {recent_value:.1f} vs 30-day baseline {mean:.1f} "
            f"(std {std:.1f}, n={n}) -> z={z:+.2f} [{band}] {direction}"
        )
        findings.append((label, z, band))

    if insufficient and not lines:
        return (
            "INSUFFICIENT DATA - the Oracle needs at least "
            f"{MIN_BASELINE_SAMPLES} baseline samples and one recent reading per "
            f"signal. Missing: {'; '.join(insufficient)}. "
            "Use health_log or health_import to feed it. " + DISCLAIMER
        )

    overall = "BASELINE"
    if any(band == "HIGH" for _, _, band in findings):
        overall = "HIGH"
    elif any(band == "ELEVATED" for _, _, band in findings):
        overall = "ELEVATED"
    elif any(band == "WATCH" for _, _, band in findings):
        overall = "WATCH"

    header = f"HEALTH SIGNAL: {overall}"
    if overall in ("ELEVATED", "HIGH"):
        header += " - consider rest and hydration; watch for symptoms"
    lines.append(DISCLAIMER)
    if insufficient:
        lines.append("Insufficient data for: " + "; ".join(insufficient))
    return header + "\n" + "\n".join(lines)


def trend(kind: str, days: int = 14) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    samples = samples_since(kind, cutoff)
    if not samples:
        return f"No {kind} samples in the last {days} days."
    by_day: dict[str, list[float]] = {}
    for value, stamp in samples:
        by_day.setdefault(stamp[:10], []).append(value)
    lines = [f"{kind} - daily averages, last {days} days:"]
    for day in sorted(by_day):
        values = by_day[day]
        lines.append(f"  {day}: {sum(values) / len(values):.1f} ({len(values)} samples)")
    return "\n".join(lines)


def register_health_tools(registry) -> None:
    """Attach the Oracle's tools to a ToolRegistry."""

    def health_log(hrv_ms: float = 0.0, resting_hr: float = 0.0) -> str:
        saved = []
        try:
            if hrv_ms and hrv_ms > 0:
                add_sample(KIND_HRV, hrv_ms)
                saved.append(f"HRV {hrv_ms} ms")
            if resting_hr and resting_hr > 0:
                add_sample(KIND_RHR, resting_hr)
                saved.append(f"resting HR {resting_hr}")
        except (TypeError, ValueError) as exc:
            return f"ERROR: {exc}"
        if not saved:
            return "ERROR: nothing to log - pass hrv_ms and/or resting_hr"
        return "Logged " + " and ".join(saved) + "."

    def health_import(path: str, kind: str) -> str:
        try:
            count = import_csv(path, kind, workspace=registry.workspace)
        except ValueError as exc:
            return f"ERROR: {exc}"
        except OSError as exc:
            return f"ERROR: {exc}"
        return f"Imported {count} {kind} samples from {path}."

    def health_check() -> str:
        return risk_assessment()

    def health_trend(days: int = 14, kind: str = KIND_HRV) -> str:
        if kind not in KINDS:
            return f"ERROR: kind must be one of {', '.join(KINDS)}"
        return trend(kind, max(1, min(int(days), 90)))

    registry.register(
        "health_log",
        "Log tonight's HRV (milliseconds) and/or resting heart rate sample into "
        "local health storage.",
        {
            "type": "object",
            "properties": {
                "hrv_ms": {"type": "number", "description": "HRV reading in ms."},
                "resting_hr": {"type": "number", "description": "Resting heart rate in bpm."},
            },
        },
        health_log,
    )
    registry.register(
        "health_import",
        "Import a wearable CSV export (timestamp + value columns) into local "
        "health storage. kind must be 'hrv_ms' or 'resting_hr'.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the CSV file."},
                "kind": {"type": "string", "enum": list(KINDS)},
            },
            "required": ["path", "kind"],
        },
        health_import,
    )
    registry.register(
        "health_check",
        "Run the Oracle: compare recent HR/HRV against the 30-day personal "
        "baseline and report a screening risk level with sigma values. "
        "A screening heuristic, not a diagnosis.",
        {"type": "object", "properties": {}},
        health_check,
    )
    registry.register(
        "health_trend",
        "Show daily averages of a health signal over the last N days.",
        {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 90},
                "kind": {"type": "string", "enum": list(KINDS)},
            },
        },
        health_trend,
    )
