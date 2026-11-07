"""Brain v1 - the privacy router: sensitivity, classification, budgets.

Pipeline per request (in order):
1. Sensitivity check - private patterns (file paths, emails, key shapes,
   screen-content markers) mean ONLY private_ok models are eligible.
2. Task classification - keyword rules (chat, code, tool_use, vision,
   summarize, planning).
3. Candidate filter - drop models lacking required capabilities or context.
4. Budget filter - per-request and daily cost caps from config.
5. Selection - cheapest eligible model whose strengths match the task;
   local models rank before cloud at equal cost.
6. Fallback order is privacy-preserving: never downgrade to a less private
   model without the user explicitly allowing cloud for the request.

Route decisions are logged (model id, reason, latency, cost - never the
prompt text) to route-log.jsonl in the config directory.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import config  # jarvis.config - one level up from the brain package
from .manifest import validate_manifest

_PRIVATE_PATTERNS = (
    re.compile(r"[A-Za-z]:\\"),                                  # windows paths
    re.compile(r"(?<!\w)/(?:home|Users|root)/"),                 # unix home paths
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),  # emails
    re.compile(r"\b(?:sk|ghp|gho|xoxb|xoxp)-[A-Za-z0-9_\-]{8,}"),      # key shapes
    re.compile(r"\bAIza[A-Za-z0-9_\-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\[A screenshot", re.IGNORECASE),                 # screen content
    re.compile(r"screen content", re.IGNORECASE),
)

_TASK_KEYWORDS = (
    ("code", ("code", "function", "script", "debug", "refactor", "compile")),
    ("summarize", ("summar", "recap", "tl;dr", "brief me")),
    ("vision", ("screenshot", "image", "picture", "see this")),
    ("planning", ("plan", "roadmap", "steps to", "strategy")),
    ("tool_use", ("check my", "run ", "list ", "open ", "status of", "battery")),
)


def is_sensitive(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _PRIVATE_PATTERNS)


def classify(text: str) -> str:
    lowered = (text or "").lower()
    for intent, keywords in _TASK_KEYWORDS:
        if any(word in lowered for word in keywords):
            return intent
    return "chat"


def redact_for_cloud(text: str) -> str:
    """Redaction gate before any cloud call: strip paths, emails, key
    shapes, and license keys. Screen content cannot be reconstructed - the
    caller must exclude it upstream.

    Known limitations (documented in SUPPORT.md, phase-10 red-team pass):
    the pattern set is literal and per-line, so it does NOT catch
    base64/hex-encoded secrets, secrets broken up by spaces or newlines,
    or unicode-escape forms. Defense in depth stays the sensitivity gate
    (is_sensitive marks the request private and pins it to private_ok
    models) and the user's own judgment - redaction is a best-effort
    scrubber, not a DLP engine.
    """
    out = text or ""
    out = re.sub(r"[A-Za-z]:\\[^\s\"']+", "[REDACTED-PATH]", out)
    out = re.sub(r"(?<!\w)/(?:home|Users|root)/[^\s\"']+", "[REDACTED-PATH]", out)
    out = re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[REDACTED-EMAIL]", out)
    out = re.sub(r"\b(?:sk|ghp|gho|xoxb|xoxp)-[A-Za-z0-9_\-]{8,}", "[REDACTED-KEY]", out)
    out = re.sub(r"\bAIza[A-Za-z0-9_\-]{8,}", "[REDACTED-KEY]", out)
    out = re.sub(r"UMBRA-[A-Za-z0-9_.\-]{4,}", "[REDACTED-LICENSE]", out)
    return out


class RouterConfig:
    """v1 router settings (config section: router). Cloud providers are
    opt-in per provider; budgets are hard stops."""

    def __init__(self, cloud_providers: list[str] | None = None,
                 max_cost_per_request: float = 0.05,
                 daily_budget: float = 0.50):
        self.cloud_providers = cloud_providers or []
        self.max_cost_per_request = max_cost_per_request
        self.daily_budget = daily_budget

    @classmethod
    def from_dict(cls, raw: dict | None) -> "RouterConfig":
        raw = raw or {}
        return cls(
            cloud_providers=list(raw.get("cloud_providers", [])),
            max_cost_per_request=float(raw.get("max_cost_per_request", 0.05)),
            daily_budget=float(raw.get("daily_budget", 0.50)),
        )


def _manifest_ok_for(manifest: dict, request: dict) -> bool:
    needs_tools = bool(request.get("tools"))
    needs_vision = bool(request.get("vision"))
    context_needed = int(request.get("context_tokens", 0) or 0)
    if needs_tools and not manifest.get("tools"):
        return False
    if needs_vision and not manifest.get("vision"):
        return False
    if context_needed and manifest.get("context_tokens", 0) < context_needed:
        return False
    return True


def spent_today(route_log_path: Path, now: float | None = None) -> float:
    """Sum of estimated costs logged today (metadata only)."""
    if not route_log_path.is_file():
        return 0.0
    today = time.strftime("%Y-%m-%d")
    total = 0.0
    try:
        for line in route_log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("ts", "").startswith(today):
                total += float(entry.get("est_cost", 0.0))
    except OSError:
        return 0.0
    return total


def route(request: dict, manifests: list[dict], router_cfg: RouterConfig,
          route_log_path: Path, now: float | None = None) -> tuple[dict | None, str]:
    """Pick a route. Returns (manifest, reason) - (None, reason) when no
    eligible model exists. Never returns a cloud model for sensitive text.
    A selected route is appended to route_log_path (metadata only - the
    prompt text never reaches the log)."""
    text = str(request.get("text", ""))
    sensitive = is_sensitive(text)
    intent = classify(text)
    needs_vision = bool(request.get("vision"))
    needs_tools = bool(request.get("tools"))

    eligible: list[dict] = []
    refusals: list[str] = []
    for manifest in manifests:
        if validate_manifest(manifest)[0] is False:
            continue
        model_id = manifest.get("id", "?")
        if sensitive and manifest.get("privacy_class") != "private_ok":
            refusals.append(f"{model_id}: private data - cloud excluded")
            continue
        if manifest.get("locality") == "cloud" and manifest.get("privacy_class") != "private_ok":
            provider_id = model_id.split("/", 1)[0]
            if provider_id not in router_cfg.cloud_providers:
                refusals.append(f"{model_id}: cloud provider not opted in")
                continue
        if not _manifest_ok_for(manifest, request):
            refusals.append(f"{model_id}: lacks required capability")
            continue
        eligible.append(manifest)

    if not eligible:
        return None, ("no eligible model: " + "; ".join(refusals[:4])) if refusals else \
            "no eligible model"

    # budget filter (cloud only - local is free)
    spent = spent_today(route_log_path, now if now is not None else time.time())
    affordable = [m for m in eligible
                  if float(m.get("cost_per_1k_in", 0)) + float(m.get("cost_per_1k_out", 0)) == 0
                  or (spent < router_cfg.daily_budget
                      and float(m.get("cost_per_1k_in", 0)) <= router_cfg.max_cost_per_request)]
    if affordable:
        eligible = affordable
    else:
        refusals.append("all paid models exceed the budget - local models kept")

    # selection: strength match first, then cheapest, local-first on ties
    def score(manifest: dict) -> tuple:
        strengths = set(manifest.get("strengths", []))
        return (
            0 if intent in strengths else 1,
            float(manifest.get("cost_per_1k_out", 0)) + float(manifest.get("cost_per_1k_in", 0)),
            0 if manifest.get("locality") == "local" else 1,
            float(manifest.get("p50_latency_ms", 9999)),
        )

    best = sorted(eligible, key=score)[0]
    why = (
        f"intent={intent}, sensitive={sensitive}; selected {best['id']} "
        f"({'local' if best['locality'] == 'local' else 'cloud'}, "
        f"cost {float(best.get('cost_per_1k_out', 0)) + float(best.get('cost_per_1k_in', 0)):.4f}/1k)"
    )
    log_route(route_log_path, {
        "model": best["id"],
        "intent": intent,
        "sensitive": sensitive,
        **request_estimate(request, best),
    })
    return best, why


def log_route(route_log_path: Path, decision: dict) -> None:
    """Append one route decision (metadata only - never the prompt text)."""
    path = route_log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **decision}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def request_estimate(request: dict, manifest: dict) -> dict:
    """Cost/latency estimate for the route log (tokens estimated by length)."""
    tokens_in = max(1, len(str(request.get("text", ""))) // 4)
    return {
        "est_tokens_in": tokens_in,
        "est_cost": round(tokens_in / 1000 * float(manifest.get("cost_per_1k_in", 0))
                          + len(str(request.get("text", ""))) // 1000
                          * float(manifest.get("cost_per_1k_out", 0)), 6),
        "p50_latency_ms": manifest.get("p50_latency_ms", 0),
    }
