"""The single execution point for injection plans (Mark XXVII).

inject.py builds plans as pure data (argv lists + descriptions); this module
is the only place that executes them. Consequences, by design:

- Argument-list execution: plan steps are argv lists, never shell strings -
  no shell parser ever sees the target or any plan text.
- Remote ssh commands are module constants in inject.py; the target is
  regex-validated to a strict [user@]host charset before any argv exists.
- No passwords are asked for, stored, or piped.
"""

from __future__ import annotations

import subprocess
import sys


def execute_steps(steps: list[tuple[str, list[str]]], console) -> int:
    """Run plan steps in order, streaming each program's output.

    Argument-list execution: the plan's text becomes argv, not a shell
    command line. No shell parser ever sees it.
    """
    for description, argv in steps:
        console.print(f"[cyan]> {description}[/]")
        try:
            proc = subprocess.run(
                [*argv],
                shell=False,
            )
        except FileNotFoundError:
            console.print("[red]ERROR: program not found (ssh/scp/adb on PATH?)[/]")
            return 1
        if proc.returncode != 0:
            console.print(f"[red]step failed (exit {proc.returncode}).[/]")
            return 1
    return 0


def build_wheel_to_dist() -> bool:
    """Build the wheel into dist/ (pip wheel --no-deps). Returns success."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", "dist"],
        shell=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
