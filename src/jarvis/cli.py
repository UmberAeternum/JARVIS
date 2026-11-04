"""The jarvis command: first-run detection, then the chat loop.

Commands: /setup (re-run the wizard), /tools (list tools), /dryrun (toggle
simulation mode), /voice (toggle push-to-talk), /tts (toggle spoken replies),
/look [question] (one-shot screenshot + vision answer), /live (toggle live
screen sharing), /publish (guided GitHub publishing), /clear, /exit.
Subcommands: jarvis watch (ambient screen observation), jarvis wake
(hands-free voice mode).
Launch flags: --voice, --live, --dry-run.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm

from . import __version__, brain, config, publish, tools
from .agent import Agent
from .wizard import run_wizard

BANNER = (
    "[bold cyan]J.A.R.V.I.S.[/] [dim]v{version} - primary: {provider} ({model})"
    "{fallback_note}{voice_note}{vision_note}[/]"
)

try:  # optional imports for friendlier error mapping
    from openai import APIConnectionError, AuthenticationError
except ImportError:  # pragma: no cover
    APIConnectionError = AuthenticationError = ()


def _rebuild(cfg: config.Config, console: Console, registry: tools.ToolRegistry) -> tuple[Agent, dict]:
    status_box: dict = {"live": None}

    def on_status(status: str) -> None:
        console.print(f"  [dim]>> {status}[/]")

    def confirm_during_status(description: str) -> bool:
        # Pause the streaming view while asking the human a question.
        live = status_box.get("live")
        if live is not None:
            live.stop()
        try:
            return Confirm.ask(f"[yellow]{description}[/]", default=False)
        finally:
            if live is not None:
                live.start()

    chain = brain.make_brain_chain(cfg, on_status=on_status)
    agent = Agent(
        chain,
        registry,
        on_status=on_status,
        max_tool_iterations=cfg.max_tool_iterations,
        max_tokens_per_turn=cfg.max_tokens_per_turn,
    )
    return agent, status_box


def _execute_turn(
    agent: Agent, status_box: dict, console: Console, user_text: str | list
) -> str | None:
    """Run one conversational turn with live-streamed reply text.

    Returns the reply, or None when the turn was interrupted/failed (the
    error is already displayed).
    """
    streamed = {"text": ""}

    def on_delta(delta: str) -> None:
        streamed["text"] += delta
        if status_box.get("live") is not None:
            status_box["live"].update(Markdown(streamed["text"]))

    try:
        with Live(
            Markdown(""),
            console=console,
            refresh_per_second=10,
            vertical_overflow="visible",
        ) as live:
            status_box["live"] = live
            try:
                return agent.run_turn(user_text, on_text_delta=on_delta)
            finally:
                status_box["live"] = None
    except KeyboardInterrupt:
        console.print("[dim](interrupted)[/]")
        agent.messages.append({"role": "user", "content": "(interrupted by user)"})
    except AuthenticationError:
        console.print(
            "[red]The brain rejected the API key.[/] Run [bold]/setup[/] to configure a valid one."
        )
    except APIConnectionError:
        console.print(
            "[red]Cannot reach the brain.[/] For cloud: check your connection. "
            "For local: is Ollama running? ([bold]ollama serve[/])"
        )
    except Exception as exc:
        console.print(f"[red]Brain error:[/] {type(exc).__name__}: {exc}")
    return None


def _chat_loop(
    cfg: config.Config, console: Console, dry_run: bool, voice_requested: bool,
    live_requested: bool,
) -> None:
    from . import vision
    from .voice import VoiceIO, stt_available  # lazy: the voice stack is optional

    registry = tools.default_registry(
        confirm=lambda description: Confirm.ask(f"[yellow]{description}[/]", default=False),
        workspace=Path.cwd(),
        dry_run=dry_run,
        allow_screen_control=cfg.vision.screen_control,
    )
    agent, status_box = _rebuild(cfg, console, registry)

    voice: VoiceIO | None = None
    voice_active = False
    if voice_requested or cfg.voice.enabled:
        ok, reason = stt_available()
        if ok:
            voice = VoiceIO(
                stt_model=cfg.voice.stt_model,
                tts_enabled=cfg.voice.tts_enabled,
                mic_device=cfg.voice.mic_device,
                on_status=lambda status: console.print(f"  [dim]>> {status}[/]"),
            )
            voice_active = True
        else:
            console.print(f"[yellow]{reason}[/] - voice input disabled, text chat only")

    live_active = False
    if live_requested or cfg.vision.enabled:
        ok, reason = vision.available()
        if ok:
            live_active = True
            console.print(
                "[yellow]Live vision ON:[/] a screenshot of your screen travels with "
                "each turn. Privacy: frames are uploaded to your configured provider."
            )
        else:
            console.print(f"[yellow]{reason}[/] - live vision disabled")

    fallback_note = (
        f" - fallback: {cfg.brains.fallback.provider} ({cfg.brains.fallback.model})"
        if cfg.brains.fallback
        else ""
    )
    console.print(
        BANNER.format(
            version=__version__,
            provider=cfg.brains.primary.provider,
            model=cfg.brains.primary.model,
            fallback_note=fallback_note,
            voice_note=" - voice ON" if voice_active else "",
            vision_note=" - LIVE VISION ON" if live_active else "",
        )
    )
    console.print(
        "[dim]Type a request, or /setup /tools /dryrun /voice /tts /look /live /publish /clear /exit[/]"
    )

    while True:
        prompt = "[bold cyan]you [Enter=speak | type]>[/] " if voice_active else "[bold cyan]you>[/] "
        try:
            user_text = console.input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Session ended.[/]")
            return
        if not user_text and voice_active and voice is not None:
            try:
                user_text = voice.listen() or ""
            except KeyboardInterrupt:
                console.print("[dim](listening cancelled)[/]")
                continue
            if not user_text:
                console.print(f"[yellow]{voice.last_error or 'nothing heard'}[/]")
                continue
            console.print(f"  [dim]heard: {user_text}[/]")
        if not user_text:
            continue
        if user_text in ("/exit", "/quit"):
            console.print("[dim]Standing down, Sir.[/]")
            return
        if user_text == "/setup":
            cfg = run_wizard(console)
            agent, status_box = _rebuild(cfg, console, registry)
            continue
        if user_text == "/tools":
            for name in registry.descriptions():
                console.print(f"  - {name}")
            continue
        if user_text == "/dryrun":
            registry.set_dry_run(not registry.is_dry_run())
            state = "ON - tools simulate, nothing executes" if registry.is_dry_run() else "OFF"
            console.print(f"[yellow]Dry-run mode:[/] {state}")
            continue
        if user_text == "/voice":
            if voice is None:
                ok, reason = stt_available()
                if not ok:
                    console.print(f"[yellow]{reason}[/]")
                    continue
                voice = VoiceIO(
                    stt_model=cfg.voice.stt_model,
                    tts_enabled=cfg.voice.tts_enabled,
                    mic_device=cfg.voice.mic_device,
                    on_status=lambda status: console.print(f"  [dim]>> {status}[/]"),
                )
            voice_active = not voice_active
            if voice_active:
                console.print(
                    "[yellow]Voice ON:[/] press Enter on an empty line to speak "
                    "(or keep typing). /voice again to disable."
                )
            else:
                console.print("[yellow]Voice OFF[/] - text only.")
            continue
        if user_text == "/tts":
            cfg.voice.tts_enabled = not cfg.voice.tts_enabled
            if voice is not None:
                voice.tts_enabled = cfg.voice.tts_enabled
            state = "ON - replies are spoken" if cfg.voice.tts_enabled else "OFF"
            console.print(f"[yellow]Spoken replies:[/] {state}")
            continue
        if user_text == "/look" or user_text.startswith("/look "):
            ok, reason = vision.available()
            if not ok:
                console.print(f"[yellow]{reason}[/]")
                continue
            remainder = user_text[5:].strip()
            monitor = cfg.vision.monitor
            # optional monitor prefix: "/look 2 what's on the second screen"
            if remainder[:2].isdigit() or (remainder[:1].isdigit()):
                parts = remainder.split(" ", 1)
                if parts[0].isdigit() and len(parts) > 1 and parts[0] != "0":
                    monitor = int(parts[0]) - 1
                    remainder = parts[1]
            question = remainder or "Describe what is on my screen, concisely."
            try:
                image = vision.capture(
                    monitor=monitor, max_width=cfg.vision.max_width
                )
            except Exception as exc:
                console.print(f"[red]{exc}[/]")
                continue
            user_text = vision.build_vision_message(
                question + "\n[A screenshot of the user's screen is attached.]", image
            )
        elif user_text == "/live":
            ok, reason = vision.available()
            if not ok:
                console.print(f"[yellow]{reason}[/]")
                continue
            live_active = not live_active
            cfg.vision.enabled = live_active
            if live_active:
                console.print(
                    "[yellow]Live vision ON:[/] JARVIS sees your screen with every "
                    "turn. Privacy: frames are uploaded to your configured provider. "
                    "/live again to disable."
                )
            else:
                console.print("[yellow]Live vision OFF.[/]")
            continue
        if user_text == "/publish":
            publish.run(console, Path.cwd())
            continue
        if user_text == "/clear":
            agent.reset()
            console.print("[dim]Conversation cleared.[/]")
            continue
        if live_active and isinstance(user_text, str):
            try:
                image = vision.capture(
                    monitor=cfg.vision.monitor, max_width=cfg.vision.max_width
                )
                user_text = vision.build_vision_message(
                    user_text + "\n[A fresh screenshot of the user's screen is attached.]", image
                )
            except Exception as exc:
                console.print(f"[dim](live capture failed: {exc} - sending text only)[/]")
        reply = _execute_turn(agent, status_box, console, user_text)
        if reply is None:
            continue
        console.print(Panel(Markdown(reply), title="J.A.R.V.I.S.", border_style="cyan"))
        if voice_active and voice is not None and cfg.voice.tts_enabled:
            try:
                voice.speak(reply)
            except Exception as exc:
                console.print(f"[dim](speech failed: {exc})[/]")


def _wake_session(cfg: config.Config, console: Console) -> None:
    """Hands-free loop: say 'Jarvis', speak a command, get a spoken answer."""
    from .voice import VoiceIO

    registry = tools.default_registry(
        confirm=lambda description: Confirm.ask(f"[yellow]{description}[/]", default=False),
        workspace=Path.cwd(),
        allow_screen_control=cfg.vision.screen_control,
    )
    agent, status_box = _rebuild(cfg, console, registry)
    voice = VoiceIO(
        stt_model=cfg.voice.stt_model,
        tts_enabled=cfg.voice.tts_enabled,
        mic_device=cfg.voice.mic_device,
        on_status=lambda status: console.print(f"  [dim]>> {status}[/]"),
    )
    console.print(
        "[cyan]Hands-free mode.[/] Say [bold]'Jarvis'[/], then your command "
        "after the cue. Ctrl+C to stop."
    )
    console.print(
        "[dim]Privacy: wake-word detection and transcription run locally (Vosk); "
        "only the command text reaches your provider.[/]"
    )
    while True:
        try:
            command = voice.listen_wake()
        except KeyboardInterrupt:
            console.print("\n[dim]Standing down, Sir.[/]")
            return
        if not command:
            console.print(f"[yellow]{voice.last_error or 'nothing heard'}[/]")
            continue
        console.print(f"  [dim]heard: {command}[/]")
        reply = _execute_turn(agent, status_box, console, command)
        if reply is not None:
            console.print(Panel(Markdown(reply), title="J.A.R.V.I.S.", border_style="cyan"))
            try:
                voice.speak(reply)
            except Exception as exc:
                console.print(f"[dim](speech failed: {exc})[/]")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    console = Console()
    if "--version" in argv or "-V" in argv:
        console.print(f"JARVIS {__version__}")
        return 0
    if "--help" in argv or "-h" in argv:
        console.print(
            "Usage: jarvis [--voice] [--live] [--dry-run] [--version]\n"
            "       jarvis watch [--interval N] [--monitor N] [--max-iterations N]\n"
            "       jarvis wake\n"
            "       jarvis health\n"
            "       jarvis sentinel\n"
            "       jarvis face\n"
            "       jarvis portal\n"
            "  --voice     start with push-to-talk voice input (Mark II)\n"
            "  --live      start with live screen sharing (Mark III)\n"
            "  --dry-run   start in simulation mode (tools plan, never execute)\n"
            "  watch       ambient screen observation loop\n"
            "  wake        hands-free voice mode: say 'Jarvis' + command\n"
            "  health      the Oracle: HR/HRV screening report\n"
            "  sentinel    the Sentinel: reminders + morning briefing daemon\n"
            "  face        the Avatar: local web face + chat (Mark VI)\n"
            "  portal      the Portal: WebXR room for headsets (Mark VII)\n"
            "  serve       the Bridge: full agent over the LAN (Mark IX)"
        )
        return 0
    if argv and argv[0] == "watch":
        from .watch import run_watch

        return run_watch(argv[1:])
    if argv and argv[0] == "wake":
        cfg = config.Config.load()
        if cfg is None:
            cfg = run_wizard(console)
        _wake_session(cfg, console)
        return 0
    if argv and argv[0] == "health":
        from . import health

        console.print(Panel(health.risk_assessment(), title="THE ORACLE", border_style="cyan"))
        return 0
    if argv and argv[0] == "sentinel":
        from .sentinel import run_sentinel

        return run_sentinel(console)
    if argv and argv[0] == "face":
        from .avatar import run_avatar

        if config.Config.load() is None:
            console.print(
                "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] "
                "once and complete the wizard - the avatar speaks through that brain."
            )
            return 1
        return run_avatar(console)
    if argv and argv[0] == "portal":
        from .portal import run_portal

        if config.Config.load() is None:
            console.print(
                "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] "
                "once and complete the wizard - the portal speaks through that brain."
            )
            return 1
        return run_portal(console)
    if argv and argv[0] == "serve":
        from .serve import run_bridge

        if config.Config.load() is None:
            console.print(
                "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] "
                "once and complete the wizard - the bridge exposes that brain."
            )
            return 1
        return run_bridge(console)

    dry_run = "--dry-run" in argv
    voice_requested = "--voice" in argv
    live_requested = "--live" in argv
    cfg = config.Config.load()
    if cfg is None:
        cfg = run_wizard(console)
    _chat_loop(
        cfg, console, dry_run=dry_run, voice_requested=voice_requested,
        live_requested=live_requested,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
