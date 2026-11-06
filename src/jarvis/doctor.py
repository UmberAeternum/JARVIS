"""Mark Brain v0 - jarvis doctor: one command that finds what is broken.

Checks (each with a fix hint when it fails):
- Python version (3.10+)
- configuration present and valid
- license tier (informational; PRO hint when LITE)
- local brain reachability + configured model presence
- update-manifest reachability (short timeout, offline-safe)
- EDITH ledger integrity

Exit code is always 0 - doctor is a report, not a gate.
"""

from __future__ import annotations

import sys

from . import config
from .config import BrainConfig

FIXES = {
    "config": "run [bold]python -m jarvis[/] (or jarvis setup) to create the configuration",
    "ollama": "start it with [bold]ollama serve[/] and pull a chat model, then run "
              "jarvis setup --yes --local --base-url http://localhost:11434/v1 --model <model>",
    "model": "pull it with [bold]ollama pull <model>[/] or switch with "
             "jarvis settings set brains.primary.model=<model>",
    "updates": "offline is fine - this only disables the update check until the "
               "network returns",
    "ledger": "jarvis access log shows the corrupted line - restore it from a backup "
              "or truncate the file (the chain will mark old entries)",
}


def _check_python(console) -> tuple[bool, str]:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 10)
    return ok, f"Python {version}" + ("" if ok else " - 3.10+ required: upgrade Python")


def _check_config(console) -> tuple[bool, str]:
    loaded = config.Config.load()
    if loaded is None:
        return False, "no configuration yet - " + FIXES["config"]
    primary = loaded.brains.primary
    return True, f"config OK - brain: {primary.provider} ({primary.model or 'model unset'})"


def _check_license(console) -> tuple[bool, str]:
    from . import licensing

    tier = licensing.tier()
    if tier == "pro":
        payload, _ = licensing.validate_license(licensing.stored_key())
        licensed_to = (payload or {}).get("name", "")
        return True, f"license: PRO ({licensed_to})"
    return True, "license: LITE (free) - PRO features need jarvis license activate <key>"


def _check_brain(console) -> tuple[bool, str]:
    from .brain import discover_local_servers, list_ollama_models

    cfg = config.Config.load()
    if cfg is None:
        return False, "no config - " + FIXES["config"]
    primary = cfg.brains.primary
    if primary.type != "local":
        key = primary.api_key or config.load_key("primary") or ""
        return (bool(primary.api_key),
                f"cloud brain {primary.provider}: key "
                + ("present" if primary.api_key else "MISSING - re-run jarvis setup"))
    servers = discover_local_servers()
    if not servers:
        return False, "no local AI server reachable - " + FIXES["ollama"]
    for server in servers:
        if primary.model in server["models"]:
            return True, f"local brain OK - {primary.model} on {server['base_url']}"
    return False, (f"model {primary.model!r} not on the local server - " + FIXES["model"]
                   + f" (available: {', '.join(servers[0]['models'])})")


def _check_updates(console) -> tuple[bool, str]:
    from .updates import check_for_update

    result = check_for_update(_current_version())
    if result.get("update_available"):
        return True, f"update available: {result['latest']} - jarvis update check for details"
    if "up to date" in str(result.get("reason", "")):
        return True, f"updates: {result['reason']}"
    return True, f"update check skipped: {result.get('reason', 'offline')}"


def _current_version() -> str:
    from . import __version__

    return __version__


def _check_ledger(console) -> tuple[bool, str]:
    from .access import status_text, verify_log

    if verify_log():
        return True, "EDITH ledger integrity OK - " + status_text().splitlines()[0]
    return False, "EDITH ledger TAMPERED - " + FIXES["ledger"]


def run_doctor(console) -> int:
    from rich.panel import Panel

    checks = [
        ("Python", _check_python),
        ("Config", _check_config),
        ("License", _check_license),
        ("Brain", _check_brain),
        ("Updates", _check_updates),
        ("EDITH ledger", _check_ledger),
    ]
    lines = []
    failures = 0
    for name, check in checks:
        try:
            ok, detail = check(console)
        except Exception as exc:
            ok, detail = False, f"check crashed: {type(exc).__name__}: {exc}"
        mark = "[green]PASS[/]" if ok else "[red]FAIL[/]"
        failures += 0 if ok else 1
        lines.append(f"  [{mark}] {name}: {detail}")
    console.print(Panel("\n".join(lines), title="UMBRA DOCTOR", border_style="cyan"))
    if failures:
        console.print(f"[yellow]{failures} check(s) need attention - hints above.[/]")
    else:
        console.print("[green]All checks passed, Sir.[/]")
    return 0
