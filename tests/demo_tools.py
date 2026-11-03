"""Live demonstration of the tool harness - real dispatches through ToolRegistry.

Run: python tests/demo_tools.py

Shows, in order:
1. system_status        - real psutil read
2. list_dir             - real listing, workspace-scoped
3. run_command (safe)   - real execution of a harmless command
4. run_command (denylisted payload) - the confirmation gate intercepts; the
   scripted operator declines, so nothing executes
5. write_file outside the workspace - the write gate intercepts, nothing writes
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jarvis.tools import default_registry  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]


def show(title: str, out: str) -> None:
    print(f"\n=== {title} ===")
    print(out)


def scripted_operator(description: str) -> bool:
    """Stand in for the human at the confirmation gate: show the prompt, decline."""
    print(f"\n>>> [CONFIRMATION GATE] {description}")
    print(">>> scripted operator: DECLINE")
    return False


reg = default_registry(confirm=scripted_operator, workspace=PROJECT)

show("1. tool: system_status (real)", reg.dispatch("system_status", "{}"))
show("2. tool: list_dir (real, workspace-scoped)",
     reg.dispatch("list_dir", json.dumps({"path": "src/jarvis", "depth": 1})))
show("3. tool: run_command (real, safe)",
     reg.dispatch("run_command", json.dumps({"command": f"{sys.executable} --version"})))
show("4. tool: run_command (denylisted payload -> gate intercepts)",
     reg.dispatch("run_command",
                  json.dumps({"command": "reg add HKCU\\Software\\JarvisDemo /v demo /d 1"})))
show("5. tool: write_file outside workspace (gate intercepts)",
     reg.dispatch("write_file",
                  json.dumps({"path": str(Path.home() / "jarvis-demo-must-not-exist.txt"),
                              "content": "x"})))

sentinel = Path.home() / "jarvis-demo-must-not-exist.txt"
print("\n=== Gate integrity check ===")
print(f"denied write created a file: {sentinel.exists()} (must be False)")
print("\nDemo complete.")
