"""Deliberate, gated program runner for JARVIS.

v1 runs executables directly: the command line is parsed into program plus
arguments and passed to subprocess as an argument list with shell=False.
Consequences, by design:

- cmd.exe builtins (dir, cd, copy, echo chains) are NOT available; the file
  and search tools cover those needs.
- Shell operators (|, &&, >, <, &) are rejected before anything runs, so no
  model-controlled text is ever parsed by a shell.
- The safety denylist + confirmation gate still guard program-level dangers
  (reg.exe, shutdown.exe, format.com are plain executables too).
- A hard timeout and output truncation bound every run.

Disable entirely with tools.default_registry(allow_shell=False).
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from . import safety

ConfirmFn = Callable[[str], bool]

COMMAND_TIMEOUT_S = 30
MAX_OUTPUT_CHARS = 8000

# A single & is also a cmd.exe command separator; rejecting it (and pipes and
# redirections) keeps the model's text out of any shell parser.
_SHELL_OPERATORS = ("&&", "||", "|", ">>", ">", "<", "&")


def _resolve_program(program: str) -> str | None:
    if any(sep in program for sep in "\\/"):
        path = Path(program).expanduser()
        return str(path) if path.is_file() else None
    return shutil.which(program)  # honours PATHEXT on Windows


def make_run_command(
    confirm: ConfirmFn,
    cwd: str | None = None,
    is_dry_run: Callable[[], bool] | None = None,
) -> Callable[[str], str]:
    """Build the run_command handler around a confirmation callback."""

    def run_command(command: str) -> str:
        if is_dry_run and is_dry_run():
            return (
                f"(dry-run) would run: {command}\n"
                "(impact: executes the program directly with the parsed arguments, no shell)"
            )
        if not command or not command.strip():
            return "ERROR: empty command"
        if any(op in command for op in _SHELL_OPERATORS):
            return (
                "ERROR: shell operators (|, &&, >, <) are not supported by this tool; "
                "run a single program with arguments, or use the file/search tools."
            )
        dangerous, reason = safety.check_command(command)
        if dangerous:
            approved = confirm(f'Command "{command}" looks dangerous ({reason}). Run it anyway?')
            if not approved:
                return "BLOCKED: the user declined this command."
        try:
            tokens = [t.strip('"') for t in shlex.split(command, posix=False)]
        except ValueError as exc:
            return f"ERROR: could not parse command: {exc}"
        if not tokens:
            return "ERROR: empty command"
        program, args = tokens[0], tokens[1:]
        resolved = _resolve_program(program)
        if resolved is None:
            return (
                f"ERROR: program not found: {program}. Note: cmd.exe builtins "
                "(dir, cd, copy, ...) are not supported; use the list_dir, "
                "read_file and write_file tools for file work."
            )
        try:
            # Argument-list execution: the model's text becomes argv, not a
            # shell command line. No shell parser ever sees it.
            proc = subprocess.run(
                [resolved, *args],
                shell=False,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_S,
                errors="replace",
                cwd=cwd,
            )
        except FileNotFoundError:
            return f"ERROR: program not found: {program}"
        except PermissionError:
            return f"ERROR: permission denied running: {program}"
        except subprocess.TimeoutExpired:
            return f"ERROR: command timed out after {COMMAND_TIMEOUT_S} s"
        output = proc.stdout or ""
        if proc.stderr:
            output += ("\n[stderr]\n" if output else "[stderr]\n") + proc.stderr
        if not output.strip():
            output = f"(no output, exit code {proc.returncode})"
        return f"exit code: {proc.returncode}\n{safety.truncate_output(output, MAX_OUTPUT_CHARS)}"

    return run_command


def register_shell_tool(registry) -> None:
    """Add the run_command tool to a ToolRegistry."""
    registry.register(
        "run_command",
        "Run a program with arguments (direct execution, no shell; cmd.exe "
        "builtins and pipes are not supported). Destructive programs require "
        "the user's confirmation.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Program name or path plus arguments."}
            },
            "required": ["command"],
        },
        make_run_command(
            registry.confirm, cwd=str(registry.workspace), is_dry_run=registry.is_dry_run
        ),
    )
