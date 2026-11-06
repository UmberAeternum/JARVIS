"""Mark XXIX - the boot sequence: a 10-second "System online, Sir." intro.

`jarvis intro` prints staged HUD lines with optional spoken bookends
(pyttsx3 when present). Skippable: Enter or Ctrl+C jumps to the end.
--no-audio runs without any TTS dependency (tests: pass stage_s=0).
Pure presentation - nothing here mutates state.
"""

from __future__ import annotations

import sys
import threading
import time

from rich.panel import Panel

STAGES = (
    "[dim] initializing core...[/]",
    "[dim] loading personality pack...[/]",
    "[dim] memory ... [green]ONLINE[/]",
    "[dim] health signals ... [green]ONLINE[/]",
    "[dim] tool gates ... [green]ARMED[/]",
    "[dim] sentinel ... [green]STANDING BY[/]",
    "[dim] watchtower ... [green]STANDING BY[/]",
    "[dim] dashboard ... [green]READY[/]",
    "[dim] bridge ... [green]READY[/]",
    "[dim] portal ... [green]READY[/]",
    "[dim] overlay ... [green]READY[/]",
    "[bold cyan] all systems nominal.[/]",
)

SPOKEN_BOOKEND = "System online, Sir."


def run_intro(console, audio: bool = True, stage_s: float = 0.8) -> int:
    """Print the boot sequence. Enter or Ctrl+C skips to the end; --no-audio
    (audio=False) removes the TTS dependency entirely. Always exits 0."""
    spoken = False
    if audio:
        try:
            import pyttsx3

            def speak_bookend() -> None:
                try:
                    engine = pyttsx3.init()
                    engine.say(SPOKEN_BOOKEND)
                    engine.runAndWait()
                except Exception:
                    pass  # the visual intro never depends on audio

            threading.Thread(target=speak_bookend, daemon=True).start()
            spoken = True
        except Exception:
            spoken = False  # no TTS stack - text only

    skip = threading.Event()

    def wait_for_enter() -> None:
        try:
            # Only a real keystroke skips; EOF ("" - redirected/piped stdin,
            # CI) must not truncate the boot sequence.
            if sys.stdin.read(1):
                skip.set()
        except Exception:
            pass

    if sys.stdin is not None and hasattr(sys.stdin, "read"):
        threading.Thread(target=wait_for_enter, daemon=True).start()

    try:
        console.print(Panel("[bold cyan]UMBRA BOOT SEQUENCE[/]", border_style="cyan"))
        for line in STAGES:
            console.print(line)
            if skip.wait(timeout=stage_s):
                break
        if skip.is_set():
            console.print("[dim](boot skipped)[/]")
        console.print(
            Panel(
                f"[bold cyan]{SPOKEN_BOOKEND}[/]" + ("  [dim](spoken)[/]" if spoken else "  [dim](audio off)[/]"),
                border_style="cyan",
            )
        )
    except KeyboardInterrupt:
        console.print("[dim](boot skipped)[/]")
    return 0
