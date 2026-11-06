"""Phase 6 - planner mode: turn a goal into gated, ledgered steps.

Two halves:

plan_goal() sends the goal to the brain with a planning prompt and parses
the reply as a JSON array of steps [{"step": str, "requires": tier}] where
tier is one of the spine's tiers (observe | assist | act | install). A
reply that is not a valid step plan falls back to a single-step plan
carrying the goal itself - the planner never invents authority the reply
did not grant: a step with a missing or bogus tier either gets the least
tier (observe) or keeps the bogus scope, which the spine default-denies at
the install tier.

execute_plan() walks the steps through the authorize chokepoint: every step
is authorized as "plan.step" with the step's tier as the scope (actor:
agent - models propose, the spine decides). A denied step stops the plan
and is recorded. Steps at the act/install tiers additionally ask the human
Confirm gate before they count as executed. Every processed step is written
to the tamper-evident access ledger, and the authorizer's own decision
(reach_allowed / reach_denied) lands there too - two honest records per
step: the policy verdict and the plan progress.

The planner never executes tools. Steps are declarative; their execution is
a separate, separately-authorized act.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from .brain.router import is_sensitive

# The spine's tier ladder (jarvis.access.TIERS) - redeclared here as planner
# vocabulary; the spine remains the single authority on what a tier unlocks.
TIERS = ("observe", "assist", "act", "install")

Authorizer = Callable[..., tuple[bool, str]]
Confirm = Callable[[str], bool]

_LEDGER_TARGET_MAX = 120  # the ledger records targets, not essays


def _planning_prompt(goal: str, manifests, router_cfg) -> str:
    """The planning prompt. Deployment context (manifests, cloud opt-ins)
    and a privacy instruction for sensitive goals keep the plan honest and
    ledger-safe."""
    cloud = ", ".join(list(getattr(router_cfg, "cloud_providers", []) or [])) or "none"
    manifest_count = len([m for m in (manifests or []) if isinstance(m, dict)])
    context = (f"Deployment context: {manifest_count} model manifest(s) available; "
               f"cloud providers opted in: {cloud}.")
    privacy = ""
    if is_sensitive(goal):
        privacy = (
            "\nIMPORTANT: the goal contains private data. Do NOT repeat paths, "
            "emails, keys or file contents verbatim in steps - the plan is "
            "recorded in an append-only ledger; describe such details abstractly."
        )
    return (
        "You are UMBRA's planner. Break the user's goal into concrete, ordered steps.\n"
        "Reply with ONLY a JSON array - no prose, no markdown fences. Each element is:\n"
        '  {"step": "<one concrete action>", "requires": "<tier>"}\n'
        "Tiers, least to most privilege: observe (look/read), assist (draft/chat), "
        "act (change files, apps or settings), install (system-level changes).\n"
        f"{context}{privacy}\n"
        f"Goal: {goal}"
    )


def _parse_steps(reply: str) -> list[dict] | None:
    """Parse the brain's reply into steps. Accepts a bare JSON array, a
    markdown-fenced array, or prose wrapping an array. Returns None when no
    valid step plan can be extracted (caller falls back)."""
    text = str(reply or "").strip()
    if not text:
        return None
    candidates = [text]
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        candidates.append(fence.group(1).strip())
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for blob in candidates:
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        if not isinstance(data, list):
            continue
        steps: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            step_text = item.get("step")
            if not isinstance(step_text, str) or not step_text.strip():
                continue
            requires = item.get("requires", "observe")
            if not isinstance(requires, str) or not requires.strip():
                requires = "observe"  # least tier for an unspecified step
            elif requires.strip().lower() in TIERS:
                requires = requires.strip().lower()
            else:
                # keep the model's value verbatim: the spine maps unknown
                # scopes to the action's tier and default-denies them
                requires = requires.strip()
            steps.append({"step": step_text.strip(), "requires": requires})
        if steps:
            return steps  # an empty array is not a plan - keep looking
    return None


def plan_goal(goal: str, chain, manifests, router_cfg) -> list[dict]:
    """Send the goal to the brain with a planning prompt and return the
    parsed step plan. The chat turn is pure: no tool schemas are offered,
    so planning can never call a tool. A reply that is not a valid JSON
    step plan falls back to a single-step plan carrying the goal."""
    goal = str(goal or "").strip()
    prompt = _planning_prompt(goal, manifests, router_cfg)
    response = chain.create_chat(messages=[{"role": "user", "content": prompt}])
    reply = ""
    try:
        reply = (response.choices[0].message.content or "")
    except (AttributeError, IndexError, TypeError):
        reply = ""
    steps = _parse_steps(reply)
    if steps is None:
        return [{"step": goal or "(empty goal)", "requires": "assist"}]
    return steps


def execute_plan(steps: list[dict], authorizer: Authorizer, confirm: Confirm | None,
                 console=None) -> list[dict]:
    """Run the plan through the authorize chokepoint, step by step.

    - Every step calls authorizer("plan.step", target=step_text,
      scope=step["requires"], actor="agent"). A denial records the denial
      and STOPS the plan.
    - act/install tiers additionally ask Confirm first; declining stops
      the plan too.
    - Every processed step is written to the access ledger (plan.step) on
      top of the authorizer's own reach_allowed/reach_denied entry.
    - Empty step texts are skipped (recorded, not authorized).

    Returns one result record per processed step:
    {"index", "step", "requires", "status", "reason", "confirmed"} with
    status in {executed, denied, declined, skipped}."""
    from . import access  # the ledger - never breaks the caller

    results: list[dict] = []

    def _record(index: int, step_text: str, tier: str, status: str,
                reason: str, confirmed: bool) -> dict:
        entry = {"index": index, "step": step_text, "requires": tier,
                 "status": status, "reason": reason, "confirmed": confirmed}
        results.append(entry)
        detail = f"{status} ({tier}) -> {step_text[:_LEDGER_TARGET_MAX]}" if step_text \
            else f"{status} ({tier}) - empty step text"
        access.log_append("plan.step", detail, actor="agent")
        if console is not None:
            style = {"executed": "green", "denied": "red", "declined": "yellow",
                     "skipped": "dim"}.get(status, "white")
            console.print(f"  [{style}]{index}. {status}[/]"
                          + (f" ({tier}) {step_text}" if step_text else f" ({tier})")
                          + (f" - {reason}" if reason and status in ("denied", "declined") else ""))

    for index, step in enumerate(steps or [], 1):
        if not isinstance(step, dict):
            step = {}
        step_text = str(step.get("step", "") or "").strip()
        tier = str(step.get("requires", "observe") or "observe")
        if not step_text:
            _record(index, "", tier, "skipped", "empty step text", False)
            continue

        allowed, reason = authorizer("plan.step", target=step_text, scope=tier, actor="agent")
        if not allowed:
            _record(index, step_text, tier, "denied", str(reason), False)
            if console is not None:
                console.print("[yellow]plan stopped - the spine denied a step.[/]")
            break

        confirmed = False
        if tier in ("act", "install"):
            if confirm is None:
                _record(index, step_text, tier, "declined",
                        "no confirmation gate available for a dangerous step", False)
                if console is not None:
                    console.print("[yellow]plan stopped - step needs confirmation.[/]")
                break
            confirmed = bool(confirm(
                f"[yellow]Execute plan step {index} ({tier})[/]: {step_text}"))
            if not confirmed:
                _record(index, step_text, tier, "declined",
                        "the user declined the confirmation", False)
                if console is not None:
                    console.print("[yellow]plan stopped - step declined.[/]")
                break

        _record(index, step_text, tier, "executed", str(reason), confirmed)

    return results
