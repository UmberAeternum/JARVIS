"""Mark III watch mode - ambient screen observation.

`python -m jarvis watch` polls the screen on an interval, and when the frame
meaningfully changes, sends it to the vision model with a standing watch
instruction. Token cost applies only to changed screens. Each observation is
printed and, when TTS is enabled, spoken.

Privacy: changed frames are uploaded to the configured cloud provider for
description. The loop prints this notice when it starts.
"""

from __future__ import annotations

import time

from rich.console import Console
from rich.panel import Panel

from . import config as config_module
from . import vision
from .brain import make_brain_chain
from .wizard import run_wizard

WATCH_INSTRUCTION = (
    "You are J.A.R.V.I.S. watching the user's screen. In at most two sentences, "
    "describe what is on screen and anything notable: errors, popups, messages, "
    "or important changes. If it is an idle desktop with nothing of interest, "
    "say so briefly."
)


def run(
    cfg: config_module.Config,
    console: Console,
    stop_after_iterations: int | None = None,
    interval_override: int | None = None,
) -> None:
    ok, reason = vision.available()
    if not ok:
        console.print(f"[yellow]{reason}[/]")
        return

    chain = make_brain_chain(cfg, on_status=lambda status: console.print(f"  [dim]>> {status}[/]"))
    interval = max(5, int(interval_override or cfg.vision.interval_s))
    voice = None
    if cfg.voice.tts_enabled:
        from .voice import VoiceIO

        voice = VoiceIO(tts_enabled=True)

    console.print(
        f"[cyan]Watching the screen[/] every {interval}s"
        + (f", model {cfg.vision.model}" if cfg.vision.model else "")
        + " - Ctrl+C to stop."
    )
    console.print(
        "[dim]Privacy: changed frames are uploaded to your configured provider "
        "to be described.[/]"
    )

    previous: str | None = None
    iterations = 0
    try:
        while True:
            time.sleep(interval)
            try:
                image = vision.capture(
                    monitor=cfg.vision.monitor, max_width=cfg.vision.max_width
                )
            except Exception as exc:
                console.print(f"[red]capture failed:[/] {exc}")
                continue
            changed, previous = vision.changed(previous, image)
            if not changed:
                continue
            message = vision.build_vision_message(WATCH_INSTRUCTION, image)
            try:
                response = chain.create_chat(
                    messages=[
                        {"role": "system", "content": "You are J.A.R.V.I.S."},
                        message,
                    ]
                )
                text = (response.choices[0].message.content or "").strip()
            except Exception as exc:
                console.print(f"[red]vision error:[/] {type(exc).__name__}: {exc}")
                continue
            if text:
                console.print(Panel(text, title="J.A.R.V.I.S. sees", border_style="cyan"))
                if voice is not None:
                    try:
                        voice.speak(text)
                    except Exception:
                        pass
            iterations += 1
            if stop_after_iterations is not None and iterations >= stop_after_iterations:
                console.print("[dim]Watch finished (iteration cap reached).[/]")
                return
    except KeyboardInterrupt:
        console.print("[dim]Watch stopped.[/]")


def run_watch(argv: list[str] | None = None) -> int:
    """Entry point for `jarvis watch [...]`."""
    argv = list(argv or [])
    console = Console()
    interval_override: int | None = None
    max_iterations: int | None = None
    monitor: int | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--interval", "-i") and i + 1 < len(argv):
            interval_override = int(argv[i + 1])
            i += 2
        elif arg == "--max-iterations" and i + 1 < len(argv):
            max_iterations = int(argv[i + 1])
            i += 2
        elif arg == "--monitor" and i + 1 < len(argv):
            monitor = int(argv[i + 1])
            i += 2
        elif arg in ("--help", "-h"):
            console.print(
                "Usage: jarvis watch [--interval N] [--monitor N] [--max-iterations N]"
            )
            return 0
        else:
            console.print(f"[yellow]Unknown argument:[/] {arg}")
            i += 1

    cfg = config_module.Config.load()
    if cfg is None:
        cfg = run_wizard(console)
    if monitor is not None:
        cfg.vision.monitor = monitor
    run(
        cfg,
        console,
        stop_after_iterations=max_iterations,
        interval_override=interval_override,
    )
    return 0
