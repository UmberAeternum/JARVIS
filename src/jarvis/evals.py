"""Phase 2A - the eval baseline engine: prove behavior does not regress.

Scenarios are data (JSON): id, category, input, setup (tier, grants,
memory, files, confirm behavior), a scripted model reply sequence, and
predicate checks (tool_called, refused, reply_contains, memory_contains,
system_prompt_contains, ...). Checks assert the PIPELINE - correct tool,
valid arguments, gates, delivery channels - not model prose.

Two model modes:
- offline (default): a ScriptedModel replays recorded steps; deterministic,
  no network - this is what CI runs.
- live (--live): the configured provider answers; replies are recorded but
  NOT scored (model judgment needs human review). Never used in CI.

compare_results() flags regressions: any scenario that passed in the
baseline and fails now (unless marked known_failure). Known failures are
recorded honestly with a reason - never silently dropped.
"""

from __future__ import annotations

import json
import re
import time
import types
from pathlib import Path

from . import access, config, memory
from .agent import Agent
from .tools import default_registry

CATEGORIES = (
    "tool_calling",
    "gate_enforcement",
    "destructive",
    "memory",
    "prompt_injection",
    "persona",
)


def default_scenarios_dir() -> Path | None:
    """The repo's scenario directory (development/CI checkout)."""
    candidate = Path(__file__).resolve().parents[2] / "tests" / "evals" / "scenarios"
    return candidate if candidate.is_dir() else None


def load_scenarios(directory: Path, category: str | None = None) -> list[dict]:
    """Load scenario objects from every *.json file in the directory. Each
    file holds one scenario or an array of scenarios."""
    scenarios: list[dict] = []
    if not directory.is_dir():
        return scenarios
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = data if isinstance(data, list) else data.get("scenarios", [])
        for scenario in items:
            if isinstance(scenario, dict) and scenario.get("id"):
                if category is None or scenario.get("category") == category:
                    scenarios.append(scenario)
    return scenarios


class ScriptedModel:
    """Deterministic offline model: replays scripted steps in order.

    Steps: {"tool_calls": [{"name": ..., "arguments": {...}}]} or
    {"reply": "..."}. The last step repeats if the agent loops.
    """

    def __init__(self, script: list[dict]):
        self.steps = list(script) or [{"reply": "(no scripted step)"}]
        self.index = 0
        self.calls = 0

    def create_chat(self, messages=None, tools=None, tool_choice="auto", **kwargs):
        step = self.steps[min(self.index, len(self.steps) - 1)]
        self.index += 1
        self.calls += 1
        if "tool_calls" in step:
            calls = []
            for i, tc in enumerate(step["tool_calls"]):
                arguments = json.dumps(tc.get("arguments", {}))
                call_id = f"c{self.calls}_{i}"
                calls.append(types.SimpleNamespace(
                    id=call_id,
                    function=types.SimpleNamespace(name=tc["name"], arguments=arguments),
                    model_dump=lambda cid=call_id, n=tc["name"], a=arguments: {
                        "id": cid, "function": {"name": n, "arguments": a}
                    },
                ))
            message = types.SimpleNamespace(content=None, tool_calls=calls)
        else:
            message = types.SimpleNamespace(content=step.get("reply", ""), tool_calls=None)
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice], usage=None)


def _tool_calls_in(messages: list[dict]) -> list[tuple[str, dict | None]]:
    """(tool name, parsed arguments|None) for every assistant tool call."""
    out: list[tuple[str, dict | None]] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for call in (msg.get("tool_calls") or []):
            fn = call.get("function", {}) if isinstance(call, dict) else {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
                if not isinstance(args, dict):
                    args = None
            except ValueError:
                args = None
            out.append((fn.get("name", ""), args))
    return out


def _tool_results_in(messages: list[dict]) -> list[str]:
    """The content of every role='tool' message - the data channel."""
    return [msg.get("content", "") for msg in messages if msg.get("role") == "tool"]


def _eval_check(check: dict, ctx: dict) -> tuple[bool, str]:
    ctype = check.get("type", "")
    if ctype == "tool_called":
        for name, args in ctx["tool_calls"]:
            if name == check.get("tool"):
                if args is None:
                    return False, "arguments were not valid JSON"
                for key, value in (check.get("args_contain") or {}).items():
                    if args.get(key) != value:
                        return False, f"argument {key} mismatch"
                return True, ""
        return False, f"tool {check.get('tool')!r} was not called"
    if ctype == "no_tool_called":
        for name, _args in ctx["tool_calls"]:
            if name == check.get("tool"):
                return False, f"tool {check.get('tool')!r} must not be called"
        return True, ""
    if ctype == "schema_valid":
        for _name, args in ctx["tool_calls"]:
            if args is None:
                return False, "tool arguments were not valid JSON"
        return True, ""
    if ctype == "reply_contains":
        needle = str(check.get("text", "")).lower()
        return (needle in ctx["reply"].lower(),
                f"reply missing {check.get('text')!r}")
    if ctype == "reply_not_contains":
        needle = str(check.get("text", "")).lower()
        return (needle not in ctx["reply"].lower(),
                f"reply contains {check.get('text')!r}")
    if ctype == "reply_matches":
        return (bool(re.search(check.get("pattern", ""), ctx["reply"])),
                f"reply does not match {check.get('pattern')!r}")
    if ctype == "confirm_asked":
        return (len(ctx["confirm_log"]) > 0,
                "the confirmation gate was never asked")
    if ctype == "tool_absent":
        return (check.get("tool") not in ctx["tools_list"],
                f"tool {check.get('tool')!r} must not exist in this tier")
    if ctype == "tool_present":
        return (check.get("tool") in ctx["tools_list"],
                f"tool {check.get('tool')!r} missing from the registry")
    if ctype == "reach_denied":
        allowed, _reason = access.authorize(check.get("action", ""))
        return (not allowed, f"reach action {check.get('action')!r} was allowed")
    if ctype == "system_prompt_contains":
        needle = str(check.get("text", "")).lower()
        return (needle in ctx["system_prompt"].lower(),
                f"system prompt missing {check.get('text')!r}")
    if ctype == "memory_contains":
        needle = str(check.get("text", "")).lower()
        notes = memory.recent_notes(200)
        return (any(needle in note.get("content", "").lower() for note in notes),
                f"memory missing {check.get('text')!r}")
    if ctype == "memory_absent":
        needle = str(check.get("text", "")).lower()
        notes = memory.recent_notes(200)
        return (not any(needle in note.get("content", "").lower() for note in notes),
                f"memory still contains {check.get('text')!r}")
    if ctype == "tool_result_role":
        needle = str(check.get("contains", "")).lower()
        results = ctx["tool_results"]
        if not results:
            return False, "no tool results were delivered"
        return (any(needle.lower() in content.lower() for content in results),
                "needle missing from the tool-result channel")
    return False, f"unknown check type: {ctype!r}"


def run_scenario(scenario: dict, root: Path) -> dict:
    """Run one scenario in an isolated config dir. Returns the result record."""
    import tempfile

    scenario_id = scenario.get("id", "unknown")
    setup = scenario.get("setup", {}) or {}
    saved = config.config_dir
    confirm_log: list[str] = []
    try:
        cfg_dir = root / f"eval-{scenario_id}"
        config.config_dir = lambda: cfg_dir

        tier = setup.get("tier", "lite")
        if tier == "pro":
            _mint_test_license(cfg_dir)
        for tier_name in setup.get("grants", []):
            access.grant_tiers([tier_name], access.CONFIRMATION_PHRASE)
        for note in setup.get("memory", []):
            memory.save_note(note)
        if setup.get("personality"):
            from .personality import save as personality_save

            personality_save(setup["personality"])
        for name, content in (setup.get("files") or {}).items():
            target = cfg_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        def confirm(description: str) -> bool:
            confirm_log.append(description)
            return bool(setup.get("confirm", False))

        registry = default_registry(
            confirm=confirm,
            workspace=cfg_dir,
            allow_screen_control=bool(setup.get("screen_control", False)),
            allow_watchtower=bool(setup.get("watchtower", False)),
        )
        model = ScriptedModel(scenario.get("script", []))
        agent = Agent(model, registry)
        started = time.time()
        reply = agent.run_turn(str(scenario.get("input", "")))
        latency_ms = int((time.time() - started) * 1000)

        ctx = {
            "tool_calls": _tool_calls_in(agent.messages),
            "tool_results": _tool_results_in(agent.messages),
            "reply": reply or "",
            "confirm_log": confirm_log,
            "tools_list": registry.descriptions(),
            "system_prompt": agent.messages[0].get("content", "") if agent.messages else "",
        }
        failures = []
        for check in scenario.get("checks", []):
            ok, detail = _eval_check(check, ctx)
            if not ok:
                failures.append(f"{check.get('type', '?')}: {detail}")
        passed = not failures
        known = bool(scenario.get("known_failure", False))
        return {
            "id": scenario_id,
            "category": scenario.get("category", "uncategorized"),
            "passed": passed,
            "known_failure": known,
            "reason": scenario.get("known_failure_reason"),
            "failures": failures,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        return {
            "id": scenario_id,
            "category": scenario.get("category", "uncategorized"),
            "passed": False,
            "known_failure": bool(scenario.get("known_failure", False)),
            "reason": scenario.get("known_failure_reason"),
            "failures": [f"harness error: {type(exc).__name__}: {exc}"],
            "latency_ms": 0,
        }
    finally:
        config.config_dir = saved


def _mint_test_license(cfg_dir: Path) -> None:
    """Generate a throwaway signer, patch the verifier, install PRO."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from . import licensing

    signer = Ed25519PrivateKey.generate()
    licensing.PUBLIC_KEY_B64 = base64.b64encode(
        signer.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    raw = json.dumps({"name": "Eval", "email": "eval@local", "tier": "pro"}).encode()
    signature = signer.sign(raw)
    key = ("UMBRA-"
           + base64.urlsafe_b64encode(raw).decode().rstrip("=")
           + "."
           + base64.urlsafe_b64encode(signature).decode().rstrip("="))
    licensing.install_license(key)


def run_scenarios(scenarios: list[dict], root: Path) -> dict:
    """Run every scenario; return the summary + per-scenario results."""
    results = [run_scenario(scenario, root) for scenario in scenarios]
    passed = sum(1 for r in results if r["passed"])
    known = sum(1 for r in results if not r["passed"] and r["known_failure"])
    failed = sum(1 for r in results if not r["passed"] and not r["known_failure"])
    return {
        "total": len(results),
        "passed": passed,
        "known_failures": known,
        "failed": failed,
        "results": results,
    }


def compare_results(baseline: dict, current: dict) -> dict:
    """Regressions: passed in baseline, failed now (unless known_failure).
    Recovered: failed in baseline, passes now. Still failing: honest list."""
    base = {r.get("id"): r for r in baseline.get("results", [])}
    regressions: list[str] = []
    recovered: list[str] = []
    still_failing: list[str] = []
    for result in current.get("results", []):
        prior = base.get(result.get("id"))
        if prior is None:
            continue
        if prior.get("passed") and not result.get("passed"):
            if not result.get("known_failure"):
                regressions.append(result["id"])
        elif not prior.get("passed") and result.get("passed"):
            recovered.append(result["id"])
        if not prior.get("passed") and not result.get("passed"):
            still_failing.append(result["id"])
    return {
        "regressions": regressions,
        "recovered": recovered,
        "still_failing": still_failing,
    }


def write_baseline(path: Path, results: dict) -> Path:
    """Record the baseline (pass/fail per scenario, latency)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "results": [
            {"id": r["id"], "category": r["category"], "passed": r["passed"],
             "known_failure": r["known_failure"], "failures": r["failures"],
             "latency_ms": r["latency_ms"]}
            for r in results["results"]
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
