"""Brain v0 - capability manifests: what each model can do, and what it costs.

A manifest is a JSON file describing one model:

    {"id": "ollama/qwen2.5:7b", "locality": "local" | "cloud",
     "context_tokens": 32768, "tools": true, "vision": false,
     "cost_per_1k_in": 0.0, "cost_per_1k_out": 0.0,
     "p50_latency_ms": 900, "strengths": ["chat", "tool_calls"],
     "privacy_class": "private_ok" | "redact_required"}

privacy_class is private_ok for local models and redact_required for cloud
models - the router's sensitivity stage relies on it. Built-in manifests
cover the default local brain; user manifests load from
<config>/manifests/*.json and are validated by the same schema.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import config

REQUIRED_FIELDS = {
    "id": str,
    "locality": str,
    "context_tokens": int,
    "tools": bool,
    "vision": bool,
    "cost_per_1k_in": (int, float),
    "cost_per_1k_out": (int, float),
    "p50_latency_ms": (int, float),
    "strengths": list,
    "privacy_class": str,
}
LOCALITY_VALUES = ("local", "cloud")
PRIVACY_VALUES = ("private_ok", "redact_required")

BUILTIN_MANIFESTS: list[dict] = [
    {
        "id": "ollama/qwen2.5:7b",
        "locality": "local",
        "context_tokens": 32768,
        "tools": True,
        "vision": False,
        "cost_per_1k_in": 0.0,
        "cost_per_1k_out": 0.0,
        "p50_latency_ms": 900,
        "strengths": ["chat", "tool_calls", "summaries"],
        "privacy_class": "private_ok",
    },
    {
        "id": "openai-compat/configured",
        "locality": "cloud",
        "context_tokens": 32768,
        "tools": True,
        "vision": False,
        "cost_per_1k_in": 0.0,
        "cost_per_1k_out": 0.0,
        "p50_latency_ms": 1500,
        "strengths": ["chat", "summaries"],
        "privacy_class": "redact_required",
    },
    {
        "id": "anthropic/claude-sonnet-4-5",
        "locality": "cloud",
        "context_tokens": 200000,
        "tools": True,
        "vision": False,
        "cost_per_1k_in": 0.003,
        "cost_per_1k_out": 0.015,
        "p50_latency_ms": 1200,
        "strengths": ["chat", "summaries"],
        "privacy_class": "redact_required",
    },
]


def validate_manifest(manifest: dict) -> tuple[bool, list[str]]:
    """Schema validation. Returns (ok, errors)."""
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return False, ["manifest must be a JSON object"]
    for field, kinds in REQUIRED_FIELDS.items():
        if field not in manifest:
            errors.append(f"missing field: {field}")
        elif not isinstance(manifest[field], kinds):
            errors.append(f"field {field} has the wrong type")
    if manifest.get("locality") not in LOCALITY_VALUES:
        errors.append(f"locality must be one of {LOCALITY_VALUES}")
    if manifest.get("privacy_class") not in PRIVACY_VALUES:
        errors.append(f"privacy_class must be one of {PRIVACY_VALUES}")
    if manifest.get("locality") == "cloud" and manifest.get("privacy_class") == "private_ok":
        errors.append("a cloud model cannot be private_ok")
    if not isinstance(manifest.get("strengths"), list) or not manifest.get("strengths"):
        errors.append("strengths must be a non-empty list")
    return (not errors), errors


def load_manifests(extra_dir: Path | None = None) -> tuple[list[dict], list[str]]:
    """Built-in manifests + user manifests from <config>/manifests/*.json.
    Returns (valid_manifests, validation_errors). Invalid files are skipped
    with their errors reported - one bad file never breaks the router."""
    manifests: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for source in (BUILTIN_MANIFESTS,):
        for manifest in source:
            ok, errs = validate_manifest(manifest)
            if ok:
                manifests.append(manifest)
                seen.add(manifest["id"])
            else:
                errors.extend(f"builtin {manifest.get('id', '?')}: {e}" for e in errs)
    if extra_dir is not None and extra_dir.is_dir():
        for path in sorted(extra_dir.glob("*.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                errors.append(f"{path.name}: unreadable ({exc})")
                continue
            ok, errs = validate_manifest(manifest)
            if not ok:
                errors.extend(f"{path.name}: {e}" for e in errs)
                continue
            if manifest["id"] in seen:
                # user manifests override built-ins with the same id
                manifests = [m for m in manifests if m["id"] != manifest["id"]]
            manifests.append(manifest)
            seen.add(manifest["id"])
    return manifests, errors


def manifests_dir() -> Path:
    return config.config_dir() / "manifests"
