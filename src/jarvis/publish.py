"""Publish JARVIS to GitHub: git/gh detection, guided repo creation.

All process launches use fixed argument lists (no shell), and every
state-changing step asks first.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt

MANUAL_STEPS = """\
Manual publishing steps (run in the project folder):

  git init
  git add -A
  git commit -m "JARVIS v1.1.0"
  git branch -M main
  git remote add origin https://github.com/<you>/JARVIS.git
  git push -u origin main

Install git:   winget install --id Git.Git -e
Install gh:    winget install --id GitHub.cli -e
Authenticate:  gh auth login\
"""


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _git_commit(console: Console, workspace: Path) -> bool:
    subprocess.run(["git", "init"], cwd=str(workspace), check=False)
    subprocess.run(["git", "add", "-A"], cwd=str(workspace), check=False)
    commit = subprocess.run(
        ["git", "commit", "-m", "JARVIS v1.1.0"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    if commit.returncode != 0:
        console.print(
            "[yellow]git commit failed[/] - configure your identity once:\n"
            "  git config --global user.name \"Your Name\"\n"
            "  git config --global user.email \"you@example.com\"\n"
            f"  {commit.stderr.strip()}"
        )
        return False
    return True


def run(console: Console, workspace: Path) -> None:
    if not _has("git"):
        console.print(
            "[yellow]git is not installed.[/] Install it with "
            "[bold]winget install --id Git.Git -e[/], then run /publish again.\n\n"
            + MANUAL_STEPS
        )
        return

    if not (workspace / ".git").exists():
        if Confirm.ask("Initialize a git repository in " + str(workspace) + "?", default=True):
            if not _git_commit(console, workspace):
                return
        else:
            console.print("Publishing cancelled - a git repository is required.")
            return

    if not _has("gh"):
        console.print(
            "[yellow]GitHub CLI (gh) is not installed.[/] Install it with "
            "[bold]winget install --id GitHub.cli -e[/], run [bold]gh auth login[/], "
            "then /publish again.\n\n" + MANUAL_STEPS
        )
        return

    auth = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True, check=False
    )
    if auth.returncode != 0:
        console.print(
            "[yellow]gh is not authenticated.[/] Run [bold]gh auth login[/] first.\n\n"
            + MANUAL_STEPS
        )
        return

    name = Prompt.ask("Repository name", default="JARVIS")
    visibility = Prompt.ask("Visibility", choices=["public", "private"], default="public")
    if not Confirm.ask(
        f"Create {visibility} repository '{name}' on GitHub and push this project?", default=False
    ):
        console.print("Publishing cancelled, Sir.")
        return

    create = subprocess.run(
        ["gh", "repo", "create", name, f"--{visibility}", "--source", ".", "--push"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    if create.returncode == 0:
        console.print(f"[green]Published to GitHub as '{name}'.[/] {create.stdout.strip()}")
    else:
        console.print(f"[red]Publishing failed:[/] {create.stderr.strip()}\n\n" + MANUAL_STEPS)
