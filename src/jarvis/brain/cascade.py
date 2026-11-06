"""Brain v2 - the cascade: cheap model first, verify, escalate on failure.

Pipeline per request:
1. The privacy router (Brain v1) picks the best route - cheapest eligible
   model whose strengths match the task, local models first, sensitive text
   pinned to private_ok models.
2. That provider's chat() runs, then a CHEAP verifier checks the reply:
   (a) the reply is non-empty; (b) when the model proposed tools, every
   proposal's arguments parse as JSON (and form an object).
3. Verification failure escalates to the next eligible route (the router
   picks it from the remaining manifests, so budget and capability rules
   still apply). One privacy rule is enforced twice: a SENSITIVE request
   never escalates to a cloud model, even if router semantics ever change.
4. Every tool proposal goes through the authorizer (the policy spine) before
   it leaves this function. Models propose; the spine decides - denied
   proposals are dropped and reported, they never reach an executor.

Every attempt is logged to the route log (metadata only - never the prompt
text). The result reports which cascade step answered and whether it was
verified, so callers can react honestly instead of guessing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .providers.base import Provider  # noqa: F401 - re-exported for typing/docs
from .router import is_sensitive, log_route, request_estimate, route

# The authorizer wraps access.authorize:
#   authorizer(action, target="", scope=None, actor="user") -> (allowed, reason)
Authorizer = Callable[..., tuple[bool, str]]

_MAX_TARGET_LEN = 200  # the ledger records targets, not essays


def _parse_arguments(raw) -> dict | None:
    """Tool-call arguments: dict passthrough, JSON string, or None."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def verify_reply(result: dict) -> tuple[bool, str]:
    """The CHEAP verifier. (a) reply non-empty; (b) proposed tool arguments
    parse as JSON objects. Returns (ok, failure_reason)."""
    reply = str((result or {}).get("reply", "") or "").strip()
    if not reply:
        return False, "empty reply"
    for call in ((result or {}).get("tool_calls") or []):
        name = str((call or {}).get("name", "?"))
        arguments = _parse_arguments((call or {}).get("arguments"))
        if arguments is None:
            return False, f"tool {name}: arguments are not valid JSON"
    return True, ""


def _authorize_proposals(result: dict, authorizer: Authorizer) -> tuple[list[dict], list[dict]]:
    """Run every tool proposal through the authorizer (the policy spine).
    Returns (authorized_proposals, denied_proposals). A denial never fails
    the reply - the spine rejects the TOOL, not the whole turn."""
    authorized: list[dict] = []
    denied: list[dict] = []
    for call in ((result or {}).get("tool_calls") or []):
        name = str((call or {}).get("name", "")).strip()
        if not name:
            continue
        arguments = _parse_arguments((call or {}).get("arguments")) or {}
        target = json.dumps(arguments, ensure_ascii=False)[:_MAX_TARGET_LEN] if arguments else name
        allowed, reason = authorizer(f"tool.{name}", target=target, scope=None, actor="agent")
        if allowed:
            authorized.append({
                "id": str((call or {}).get("id", "") or ""),
                "name": name,
                "arguments": arguments,
            })
        else:
            denied.append({"name": name, "reason": str(reason)})
    return authorized, denied


def cascade(request: dict, manifests: list[dict], router_cfg,
            route_log_path: Path, providers: dict[str, Provider],
            authorizer: Authorizer) -> dict:
    """Brain v2 entry point: best route first, verify, escalate on failure.

    request: {"text": "..."} or {"messages": [...]} plus optional "tools".
    providers: adapter map keyed by manifest id or provider id (the part
    before "/" in a manifest id, e.g. "ollama").
    authorizer: wraps access.authorize - every tool proposal passes through
    it before anything may execute.

    Returns {"reply", "route": {"model", "cascade_step", "reason"},
    "verified", "tool_calls", "denied_tools"}. verified=False with an empty
    reply means every eligible route failed verification; the reason says
    why, including when privacy blocked the escalation."""
    if "messages" in request and request.get("messages"):
        messages = list(request["messages"])
    else:
        messages = [{"role": "user", "content": str(request.get("text", ""))}]
    tools = request.get("tools")
    sensitive = is_sensitive(str(request.get("text", "")))

    remaining = [m for m in (manifests or []) if isinstance(m, dict)]
    attempts = 0
    notes: list[str] = []
    last_reply = ""
    last_model = ""
    last_reason = ""

    while remaining:
        manifest, why = route(request, remaining, router_cfg, route_log_path)
        if manifest is None:
            last_reason = str(why)
            break
        remaining = [m for m in remaining if m.get("id") != manifest.get("id")]
        model_id = str(manifest.get("id", "?"))
        provider = providers.get(model_id) or providers.get(model_id.split("/", 1)[0])
        if provider is None:
            last_reason = f"{model_id}: no provider adapter loaded"
            log_route(route_log_path, {"model": model_id, "cascade": "skipped",
                                       "reason": last_reason})
            continue

        attempts += 1
        last_model = model_id
        try:
            result = provider.chat(messages, tools)
            ok, fail_why = verify_reply(result)
        except Exception as exc:  # a dead provider is a failed attempt, not a crash
            ok, fail_why, result = False, f"{type(exc).__name__}: {exc}", {}

        log_route(route_log_path, {
            "model": model_id,
            "cascade_step": attempts,
            "verified": ok,
            **request_estimate(request, manifest),
        })
        if ok:
            authorized, denied = _authorize_proposals(result, authorizer)
            reason = f"cascade step {attempts}: verified by {model_id}"
            if notes:
                reason += f" (escalated after: {'; '.join(notes)})"
            return {
                "reply": str((result or {}).get("reply", "") or "").strip(),
                "route": {"model": model_id, "cascade_step": attempts, "reason": reason},
                "verified": True,
                "tool_calls": authorized,
                "denied_tools": denied,
            }
        last_reply = str((result or {}).get("reply", "") or "").strip()
        notes.append(f"step {attempts} ({model_id}): {fail_why}")
        last_reason = notes[-1]
        if sensitive:
            # Privacy invariant, enforced a second time on purpose: sensitive
            # text never escalates past private_ok models, whatever the
            # router does. (route() already excludes cloud for sensitive
            # text; this guard makes the rule hold on its own.)
            before = len(remaining)
            remaining = [m for m in remaining if m.get("privacy_class") == "private_ok"]
            if before != len(remaining):
                last_reason += (
                    " - sensitive request: escalation to non-private_ok "
                    "models is not permitted"
                )

    if sensitive and attempts and not remaining:
        last_reason += " - no privacy-safe escalation available"
    return {
        "reply": last_reply,
        "route": {"model": last_model or "?", "cascade_step": attempts,
                  "reason": f"cascade exhausted - {last_reason or 'no eligible model'}"},
        "verified": False,
        "tool_calls": [],
        "denied_tools": [],
    }
