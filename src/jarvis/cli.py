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

import json
import sys
import threading
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm

import time as _time
from datetime import datetime

from . import __version__, brain, config, conversations, licensing, publish, tools
from .agent import Agent
from .wizard import run_wizard

PRODUCT_NAME = "UMBRA"
BANNER = (
    f"[bold cyan]{PRODUCT_NAME}[/] [dim]v{{version}} - {{tier}} tier - primary: {{provider}} ({{model}})"
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


def _first_session_title() -> str:
    return "Session " + datetime.now().strftime("%Y-%m-%d %H:%M")


def _execute_turn(
    agent: Agent, status_box: dict, console: Console, user_text: str | list,
    session_id: int | None = None,
) -> str | None:
    """Run one conversational turn with live-streamed reply text.

    Returns the reply, or None when the turn was interrupted/failed (the
    error is already displayed). When session_id is set, every turn is
    logged to the local conversation store (the Second Mind).
    """
    streamed = {"text": ""}

    def on_delta(delta: str) -> None:
        streamed["text"] += delta
        if status_box.get("live") is not None:
            status_box["live"].update(Markdown(streamed["text"]))

    user_content = user_text if isinstance(user_text, str) else str(user_text)
    try:
        with Live(
            Markdown(""),
            console=console,
            refresh_per_second=10,
            vertical_overflow="visible",
        ) as live:
            status_box["live"] = live
            try:
                reply = agent.run_turn(user_text, on_text_delta=on_delta)
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
    else:
        if session_id is not None and isinstance(user_text, str):
            try:
                conversations.log_message(session_id, "user", user_text)
                conversations.log_message(session_id, "assistant", reply)
            except Exception:
                pass  # logging must never break the conversation
        return reply
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
        allow_screen_control=cfg.vision.screen_control and licensing.is_pro(),
        allow_watchtower=licensing.is_pro(),
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
            tier=licensing.tier(),
            provider=cfg.brains.primary.provider,
            model=cfg.brains.primary.model,
            fallback_note=fallback_note,
            voice_note=" - voice ON" if voice_active else "",
            vision_note=" - LIVE VISION ON" if live_active else "",
        )
    )
    console.print(
        "[dim]Type a request, or /setup /tools /history /resume N /dryrun /voice /tts /look /live /publish /clear /exit[/]"
    )

    # Mark XV - the Second Mind: every turn of this session is logged locally
    session_id = conversations.start_session(_first_session_title())

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
        if user_text == "/history":
            sessions = conversations.list_sessions()
            if not sessions:
                console.print("[dim]No sessions recorded yet.[/]")
            for session in sessions:
                console.print(
                    f"  #{session['id']} [{session['started_at']}] "
                    f"{session['title']} ({session['turns']} turns)"
                )
            console.print("[dim]/resume <id> to load a session back into context.[/]")
            continue
        if user_text.startswith("/resume"):
            parts = user_text.split(" ", 1)
            target = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            if target is None:
                console.print("[yellow]usage: /resume <session id>[/]")
                continue
            recorded = conversations.session_messages(target)
            if not recorded:
                console.print(f"[yellow]session #{target} has no messages.[/]")
                continue
            agent.reset()
            for entry in recorded:
                role = entry["role"]
                if role not in ("user", "assistant"):
                    continue
                agent.messages.append({"role": role, "content": entry["content"]})
            console.print(
                f"[green]Resumed session #{target} - {len(recorded)} messages back in context, Sir.[/]"
            )
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
            if licensing.tier() != "pro":
                console.print(
                    "[yellow]Live vision is a PRO feature.[/] "
                    "[bold]jarvis license activate <key>[/]"
                )
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
        reply = _execute_turn(agent, status_box, console, user_text, session_id=session_id)
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
        "[cyan]Hands-free mode.[/] Say [bold]'" + cfg.voice.wake_phrase + "'[/], "
        "then your command after the cue. Ctrl+C to stop."
    )
    console.print(
        "[dim]Privacy: wake-word detection and transcription run locally (Vosk); "
        "only the command text reaches your provider.[/]"
    )
    while True:
        try:
            command = voice.listen_wake(phrase=cfg.voice.wake_phrase)
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
                voice.speak(reply, barge_in=True)
            except Exception as exc:
                console.print(f"[dim](speech failed: {exc})[/]")


def _license_command(console: Console, args: list[str]) -> int:
    """jarvis license activate <key> | jarvis license status"""
    sub = args[0] if args else ""
    if sub == "status":
        tier = licensing.tier()
        key = licensing.stored_key()
        payload, _reason = licensing.validate_license(key) if key else (None, None)
        licensed_to = payload.get("name") if payload else "(no valid license)"
        console.print(
            Panel(
                f"tier: [bold]{tier}[/]\nlicensed to: {licensed_to}",
                title="LICENSE",
                border_style="cyan",
            )
        )
        if tier != "pro":
            console.print("[dim]PRO features (screen control, bridge, portal, "
                          "watchtower, live vision) need a PRO license.[/]")
        return 0
    if sub == "activate":
        key = " ".join(args[1:]).strip()
        if not key:
            console.print("[red]usage: jarvis license activate <key>[/]")
            return 1
        ok, message = licensing.install_license(key)
        if ok:
            console.print(f"[green]{message}[/]")
            return 0
        console.print(f"[red]{message}[/]")
        return 1
    console.print("usage: jarvis license activate <key> | jarvis license status")
    return 1


def _startup_update_check(cfg: config.Config, console: Console) -> None:
    """Mark XVII: one quiet background update check. Prints only when a newer
    release exists; failures go to the local log (Mark XVIII) without noise."""
    from .updates import check_for_update

    result = check_for_update(__version__, cfg.updates.manifest_url)
    if result.get("update_available"):
        console.print(
            f"[dim]Update available: [bold]{result['latest']}[/] - {result.get('url', '')} "
            "([bold]jarvis update check[/] for details)[/]"
        )
    elif "failed" in str(result.get("reason", "")):
        try:
            from .diagnostics import log_line

            log_line("update", result["reason"])
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    """Entry point with the Mark XVIII opt-in crash-report hook. With
    diagnostics.crash_reports disabled, behavior is exactly as before."""
    try:
        return _dispatch(argv)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        from .diagnostics import maybe_report_crash

        return maybe_report_crash(exc)


def _dispatch(argv: list[str] | None = None) -> int:
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
            "  serve       the Bridge: full agent over the LAN (PRO) · serve --api: local API\n"
            "  overlay     always-on-top companion beside your other apps\n"
            "  plugin      scaffold <vscode|browser> --out <dir> - app-injection starters\n"
            "  inject      scan | install | bundle - put UMBRA on another device\n"
            "  personality show | set - honorific, verbosity, humor, proactivity\n"
            "  access      grant --full | status | log | revoke --all (EDITH protocol)\n"
            "  voice       show | set <default|jarvis> - TTS voice profile\n"
            "  hud         show | theme <hologram|minimal> - dashboard HUD look\n"
            "  intro       the 10-second boot sequence (--no-audio to skip speech)\n"
            "  api         token rotate | token show - the local API credential\n"
            "  dashboard   the Mission Control: local web dashboard\n"
            "  setup       run the onboarding wizard (setup --yes for CI)\n"
            "  settings    show | set <key>=<value> | reset [--yes]\n"
            "  update      check - look for a newer signed release\n"
            "  diagnostics bundle [--include-conversations] - redacted support bundle\n"
            "  profile     list | create <name> | use <name> | delete <name>\n"
            "  export      [--profile name] [--out file] [--include-secrets]\n"
            "  import      <file.json> - restore an export into the active profile\n"
            "  license     activate <key> | status - PRO licensing"
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
    if argv and argv[0] == "license":
        return _license_command(console, argv[1:])
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
        if licensing.tier() != "pro":
            console.print(
                "[yellow]The Portal is a PRO feature.[/] Install a PRO license "
                "with [bold]jarvis license activate <key>[/]."
            )
            return 1
        return run_portal(console)
    if argv and argv[0] == "serve":
        if "--api" in argv[1:]:
            # Mark XXVI: the embeddable local API - loopback + token, the same
            # trust envelope as the dashboard (LITE); the LAN Bridge stays PRO.
            from .api import run_api

            if config.Config.load() is None:
                console.print(
                    "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] "
                    "once and complete the wizard - the API speaks through that brain."
                )
                return 1
            return run_api(console)
        from .serve import run_bridge

        if config.Config.load() is None:
            console.print(
                "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] "
                "once and complete the wizard - the bridge exposes that brain."
            )
            return 1
        if licensing.tier() != "pro":
            console.print(
                "[yellow]The Bridge is a PRO feature.[/] Install a PRO license "
                "with [bold]jarvis license activate <key>[/]."
            )
            return 1
        return run_bridge(console)
    if argv and argv[0] == "api":
        from .api import load_token, token_path

        sub = argv[1] if len(argv) > 1 else ""
        arg2 = argv[2] if len(argv) > 2 else ""
        if sub == "token" and arg2 == "rotate":
            from .api import rotate_token

            console.print("[green]API token rotated.[/] Shown once - store it in your client:")
            console.print(rotate_token())
            return 0
        if sub == "token" and arg2 == "show":
            from .config import mask_key

            console.print(f"token: {mask_key(load_token())}\nfile: {token_path()}")
            return 0
        console.print("usage: jarvis api token rotate | jarvis api token show")
        return 1
    if argv and argv[0] == "overlay":
        from .overlay import run_overlay

        rest = argv[1:]
        attach = None
        if "--attach" in rest:
            index = rest.index("--attach")
            if index + 1 < len(rest):
                attach = rest[index + 1]
        return run_overlay(
            console,
            attach_name=attach,
            no_ui="--no-ui" in rest,
            clickthrough="--clickthrough" in rest,
        )
    if argv and argv[0] == "plugin":
        from .plugins import scaffold_browser, scaffold_vscode

        rest = argv[1:]
        if (rest[0] if rest else "") != "scaffold" or len(rest) < 3:
            console.print("usage: jarvis plugin scaffold <vscode|browser> --out <dir>")
            return 1
        kind = rest[1]
        out_dir: Path | None = None
        if "--out" in rest:
            index = rest.index("--out")
            if index + 1 < len(rest):
                out_dir = Path(rest[index + 1])
        if out_dir is None:
            console.print("[red]--out <dir> is required[/]")
            return 1
        if kind == "vscode":
            files = scaffold_vscode(out_dir)
        elif kind == "browser":
            files = scaffold_browser(out_dir)
        else:
            console.print("[red]unknown scaffold kind - use vscode or browser[/]")
            return 1
        for written in files:
            console.print(f"  wrote {written}")
        console.print(
            "[dim]Scaffold only - no auto-install. Configure the token in the\n"
            "host's own settings at runtime; see the generated README.[/]"
        )
        return 0
    if argv and argv[0] == "access":
        from . import access

        sub = argv[1] if len(argv) > 1 else "status"
        if sub == "grant":
            if "--full" not in argv[2:]:
                console.print("usage: jarvis access grant --full")
                return 1
            console.print("[yellow]This grants UMBRA full reach: device installs,")
            console.print("[yellow]cross-app attachment, and the API's tool endpoints.")
            console.print(f"[yellow]The grant expires in {access.window_hours()}h and is logged.")
            typed = console.input("[bold cyan]Type the confirmation phrase> [/]")
            ok, message = access.grant_full(typed)
            console.print(f"[{'green' if ok else 'red'}]{message}[/]")
            return 0 if ok else 1
        if sub == "status":
            console.print(access.status_text())
            return 0
        if sub == "log":
            entries = access.log_entries()
            if not entries:
                console.print("[dim]The access ledger is empty.[/]")
                return 0
            for entry in entries[-40:]:
                mark = "" if entry.get("integrity") == "ok" else " [red]" + entry.get("integrity", "") + "[/]"
                console.print(f"  [{entry.get('ts', '?')}] {entry.get('action', '?')}: {entry.get('detail', '')}{mark}")
            console.print("[dim]integrity: " + ("OK" if access.verify_log() else "TAMPERED") + "[/]")
            return 0
        if sub == "revoke":
            if "--all" not in argv[2:]:
                console.print("usage: jarvis access revoke --all")
                return 1
            console.print("[green]" + access.revoke_all() + "[/]")
            return 0
        console.print("usage: jarvis access grant --full | status | log | revoke --all")
        return 1
    if argv and argv[0] == "voice":
        from .config import VoiceConfig

        sub = argv[1] if len(argv) > 1 else "show"
        current = config.Config.load() or config.Config()
        if sub == "show":
            profile = current.voice.profile or "(system default)"
            console.print(f"TTS profile: {profile}\nprofiles: system default, jarvis (British butler)")
            return 0
        if sub == "set":
            if len(argv) < 3:
                console.print("usage: jarvis voice set <default|jarvis>")
                return 1
            profile = argv[2].strip().lower()
            if profile in ("default", "system"):
                profile = ""
            if profile not in ("", "jarvis"):
                console.print("[red]unknown profile - use default or jarvis[/]")
                return 1
            current.voice.profile = profile
            current.save()
            console.print(f"[green]TTS profile set:[/] {profile or 'system default'}"
                          " (British-butler voice used when a matching SAPI voice exists)")
            return 0
        console.print("usage: jarvis voice show | set <default|jarvis>")
        return 1
    if argv and argv[0] == "hud":
        sub = argv[1] if len(argv) > 1 else "show"
        current = config.Config.load() or config.Config()
        if sub == "show":
            console.print(
                f"theme: {current.hud.theme} · sound: {current.hud.sound} · "
                f"typed: {current.hud.typed} · boot: {current.hud.boot}"
            )
            return 0
        if sub == "theme":
            if len(argv) < 3 or argv[2] not in ("hologram", "minimal"):
                console.print("usage: jarvis hud theme <hologram|minimal>")
                return 1
            current.hud.theme = argv[2]
            current.save()
            console.print(f"[green]HUD theme:[/] {current.hud.theme}")
            return 0
        console.print("usage: jarvis hud show | theme <hologram|minimal>")
        return 1
    if argv and argv[0] == "intro":
        from .intro import run_intro

        return run_intro(console, audio="--no-audio" not in argv[1:])
    if argv and argv[0] == "personality":
        from .personality import load, save

        sub = argv[1] if len(argv) > 1 else "show"
        if sub == "show":
            values = load()
            console.print(
                f"honorific: {values['honorific']} · verbosity: {values['verbosity']} · "
                f"humor: {values['humor']}/10 · proactive: {values['proactive']}/2"
            )
            console.print("[dim]set with: jarvis personality set --honorific X --verbosity concise|normal|chatty --humor 0-10 --proactive 0-2[/]")
            return 0
        if sub == "set":
            rest = argv[2:]
            updates: dict = {}
            for flag, key in (("--honorific", "honorific"), ("--verbosity", "verbosity")):
                if flag in rest:
                    index = rest.index(flag)
                    if index + 1 < len(rest):
                        updates[key] = rest[index + 1]
            for flag, key in (("--humor", "humor"), ("--proactive", "proactive")):
                if flag in rest:
                    index = rest.index(flag)
                    if index + 1 < len(rest):
                        try:
                            updates[key] = int(rest[index + 1])
                        except ValueError:
                            console.print(f"[red]{flag} needs an integer[/]")
                            return 1
            if not updates:
                console.print("usage: jarvis personality set [--honorific X] [--verbosity V] [--humor 0-10] [--proactive 0-2]")
                return 1
            try:
                values = save(updates)
            except ValueError as exc:
                console.print(f"[red]{exc}[/]")
                return 1
            console.print(
                f"[green]Personality saved.[/] honorific: {values['honorific']} · "
                f"verbosity: {values['verbosity']} · humor: {values['humor']}/10 · "
                f"proactive: {values['proactive']}/2"
            )
            return 0
        console.print("usage: jarvis personality show | set [...]")
        return 1
    if argv and argv[0] == "inject":
        from .inject import run_inject

        return run_inject(console, argv[1:])
    if argv and argv[0] == "profile":
        from .profiles import create_profile, delete_profile, list_profiles, use_profile

        sub = argv[1] if len(argv) > 1 else "list"
        try:
            if sub == "list":
                rows = [
                    f"  {entry['name']}{' [active]' if entry['active'] else ''}  -  {entry['path']}"
                    for entry in list_profiles()
                ]
                console.print(Panel("\n".join(rows), title="PROFILES", border_style="cyan"))
                console.print(
                    "[dim]Each profile has its own brain config, memories, "
                    "conversations, health data and license.[/]"
                )
                return 0
            if sub == "create":
                if len(argv) < 3:
                    console.print("usage: jarvis profile create <name>")
                    return 1
                created = create_profile(argv[2])
                console.print(
                    f"[green]Profile '{created['name']}' created at[/] {created['path']}\n"
                    f"[dim]Switch with[/] [bold]jarvis profile use {created['name']}[/]"
                    " [dim]- the first run there starts the setup wizard.[/]"
                )
                return 0
            if sub == "use":
                if len(argv) < 3:
                    console.print("usage: jarvis profile use <name>")
                    return 1
                name = use_profile(argv[2])
                console.print(f"[green]Active profile:[/] {name} (applies to every command from now on)")
                return 0
            if sub == "delete":
                if len(argv) < 3:
                    console.print("usage: jarvis profile delete <name> [--yes]")
                    return 1
                if "--yes" not in argv[3:]:
                    if not Confirm.ask(
                        f"Delete profile '{argv[2]}' and ALL of its data?", default=False
                    ):
                        console.print("[dim]Aborted.[/]")
                        return 1
                name = delete_profile(argv[2])
                console.print(f"[green]Profile '{name}' deleted.[/]")
                return 0
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            return 1
        console.print("usage: jarvis profile list | create <name> | use <name> | delete <name> [--yes]")
        return 1
    if argv and argv[0] == "export":
        from .portability import export_profile
        from .profiles import validate_name

        rest = argv[1:]
        source = config.active_profile()
        if "--profile" in rest:
            index = rest.index("--profile")
            if index + 1 < len(rest):
                source = rest[index + 1]
        try:
            if source != "default":
                source = validate_name(source)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            return 1
        include_secrets = "--include-secrets" in rest
        if include_secrets and not Confirm.ask(
            "Include API keys in the export? The file will contain PLAINTEXT secrets.",
            default=False,
        ):
            console.print("[dim]Aborted the secret inclusion - exporting without secrets.[/]")
            include_secrets = False
        out_flag: Path | None = None
        if "--out" in rest:
            index = rest.index("--out")
            if index + 1 < len(rest):
                out_flag = Path(rest[index + 1])
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = out_flag or Path(f"umbra-export-{source}-{stamp}.json")
        with config.using_profile(source):
            data = export_profile(include_secrets=include_secrets)
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if sys.platform != "win32" and include_secrets:
            try:
                out_path.chmod(0o600)
            except OSError:
                pass
        console.print(
            Panel(
                f"[green]Export written:[/] {out_path}\n"
                f"profile: {source}\n"
                f"secrets: {'INCLUDED - protect this file' if include_secrets else 'excluded'}\n"
                f"memories: {len(data['memories'])}  "
                f"sessions: {len(data['conversations']['sessions'])}",
                title="EXPORT",
                border_style="cyan",
            )
        )
        return 0
    if argv and argv[0] == "import":
        from .portability import import_profile, validate_export

        rest = argv[1:]
        candidates = [item for item in rest if not item.startswith("--")]
        if not candidates:
            console.print("usage: jarvis import <file.json> [--yes]")
            return 1
        source_file = Path(candidates[0])
        if not source_file.exists():
            console.print(f"[red]File not found:[/] {source_file}")
            return 1
        try:
            data = json.loads(source_file.read_text(encoding="utf-8"))
            validate_export(data)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            console.print(f"[red]Invalid export:[/] {exc}")
            return 1
        if "--yes" not in rest and not Confirm.ask(
            "Apply this export's configuration to the ACTIVE profile and add its "
            "memories and conversations? (existing data is kept; the config is replaced)",
            default=False,
        ):
            console.print("[dim]Aborted.[/]")
            return 1
        console.print(f"[green]{import_profile(data)}[/]")
        return 0
    if argv and argv[0] == "diagnostics":
        from .diagnostics import build_bundle

        rest = argv[1:]
        if (rest[0] if rest else "bundle") != "bundle":
            console.print("usage: jarvis diagnostics bundle [--include-conversations] [--out <file>]")
            return 1
        # LITE feature: local support tooling; works even before setup
        current = config.Config.load() or config.Config()
        include_conversations = "--include-conversations" in rest
        out_path: Path | None = None
        if "--out" in rest:
            index = rest.index("--out")
            if index + 1 < len(rest):
                out_path = Path(rest[index + 1])
        bundle_path = build_bundle(current, include_conversations=include_conversations, out=out_path)
        console.print(
            Panel(
                f"[green]Diagnostics bundle written:[/] {bundle_path}\n\n"
                "Redacted: no API keys, no license key, no message bodies\n"
                "(unless --include-conversations was passed - even then every\n"
                "line is scrubbed). Attach this file when requesting support.",
                title="DIAGNOSTICS",
                border_style="cyan",
            )
        )
        return 0
    if argv and argv[0] == "update":
        from .updates import check_for_update

        action = argv[1] if len(argv) > 1 else "check"
        if action == "check":
            # LITE feature: report-only, nothing is ever downloaded automatically
            result = check_for_update(__version__)
            if result.get("update_available"):
                lines = [
                    f"A new version is available: [bold cyan]{result['latest']}[/] "
                    f"(you are on {__version__})",
                ]
                if result.get("notes"):
                    lines += ["", result["notes"]]
                lines += [
                    "",
                    f"Release: {result.get('url', '(no url)')}",
                ]
                if result.get("pro_url"):
                    lines.append(f"PRO asset: {result['pro_url']}")
                lines += [
                    "",
                    "Apply it with [bold]jarvis update apply[/] (signature + hash verified),",
                    "or upgrade manually: [bold]pip install --upgrade jarvis-ai[/].",
                ]
                console.print(Panel("\n".join(lines), title="UPDATE AVAILABLE", border_style="amber"))
            else:
                console.print(
                    f"[dim]Update check: {result.get('reason', 'no update')} (current: {__version__})[/]"
                )
            return 0
        if action == "apply":
            from .ga import apply_update
            from .updates import check_for_update

            result = check_for_update(__version__)
            if not result.get("update_available"):
                console.print(f"[dim]{result.get('reason', 'no update')} - nothing to apply.[/]")
                return 0
            from .updates import DEFAULT_MANIFEST_URL

            manifest_url = result.get("manifest_url") or DEFAULT_MANIFEST_URL
            from . import safety

            try:
                raw, reason = safety.guarded_fetch_bytes(manifest_url, 64 * 1024, timeout=10.0)
            except Exception as exc:
                console.print(f"[red]manifest fetch failed: {exc}[/]")
                return 1
            import json as jsonlib

            manifest = jsonlib.loads((raw or b"{}").decode("utf-8"))
            ok, message = apply_update(manifest, __version__)
            console.print(f"[{'green' if ok else 'red'}]{message}[/]")
            return 0 if ok else 1
        if action == "rollback":
            from .ga import rollback_update

            ok, message = rollback_update()
            console.print(f"[{'green' if ok else 'red'}]{message}[/]")
            return 0 if ok else 1
        console.print("usage: jarvis update check | apply | rollback")
        return 1
    if argv and argv[0] == "payhub":
        from .ga import mark_sent, read_queue

        sub = argv[1] if len(argv) > 1 else "list"
        if sub == "serve":
            from .ga import run_payhub

            return run_payhub(console, argv[2:])
        if sub == "list":
            entries = read_queue()
            if not entries:
                console.print("[dim]The payment queue is empty.[/]")
                return 0
            for index, entry in enumerate(entries):
                flag = " [green]sent[/]" if entry.get("sent") else " [yellow]pending[/]"
                console.print(
                    f"  #{index} {entry.get('ts', '?')} {entry.get('source', '?')} "
                    f"{entry.get('email', '?')} {entry.get('product', '')}{flag}"
                )
            return 0
        if sub == "mark-sent":
            if len(argv) < 3 or not argv[2].isdigit():
                console.print("usage: jarvis payhub mark-sent <index>")
                return 1
            console.print("[green]marked sent[/]" if mark_sent(int(argv[2])) else "[red]no such entry[/]")
            return 0
        console.print("usage: jarvis payhub serve | list | mark-sent <index>")
        return 1
    if argv and argv[0] == "license":
        sub = argv[1] if len(argv) > 1 else ""
        if sub == "trial":
            from .licensing import start_trial

            ok, message = start_trial()
            console.print(f"[{'green' if ok else 'yellow'}]{message}[/]")
            return 0 if ok else 1
        return _license_command(console, argv[1:])
    if argv and argv[0] == "setup":
        from .wizard import run_wizard, setup_noninteractive

        rest = argv[1:]
        if "--yes" in rest:
            new_cfg, message = setup_noninteractive(rest)
            if new_cfg is None:
                console.print(f"[red]{message}[/]")
                return 2
            console.print(f"[green]{message}[/]")
            return 0
        run_wizard(console)
        return 0
    if argv and argv[0] == "settings":
        from .settings import apply_setting, reset_config, show_text

        sub = argv[1] if len(argv) > 1 else "show"
        if sub == "show":
            current = config.Config.load()
            if current is None:
                console.print("[yellow]No configuration yet.[/] Run [bold]jarvis setup[/].")
                return 1
            console.print(Panel(show_text(current), title="SETTINGS", border_style="cyan"))
            return 0
        if sub == "set":
            current = config.Config.load()
            if current is None:
                console.print("[yellow]No configuration yet.[/] Run [bold]jarvis setup[/].")
                return 1
            if len(argv) < 3 or "=" not in argv[2]:
                console.print("usage: jarvis settings set <key>=<value>")
                return 1
            dotted, value = argv[2].split("=", 1)
            try:
                message = apply_setting(current, dotted.strip(), value.strip())
            except KeyError:
                console.print(f"[red]Unknown setting:[/] {dotted.strip()}")
                return 1
            except ValueError as exc:
                console.print(f"[red]{exc}[/]")
                return 1
            current.save()
            console.print(f"[green]{message}[/]")
            return 0
        if sub == "reset":
            if "--yes" not in argv[2:]:
                if not Confirm.ask(
                    "Reset configuration? Brain settings are wiped; memories, "
                    "health data and your license are kept.",
                    default=False,
                ):
                    console.print("[dim]Aborted.[/]")
                    return 1
            console.print(reset_config())
            return 0
        console.print("usage: jarvis settings show | set <key>=<value> | reset [--yes]")
        return 1
    if argv and argv[0] == "dashboard":
        from .dashboard import run_dashboard

        if config.Config.load() is None:
            console.print(
                "[yellow]No brain configured yet.[/] Run [bold]python -m jarvis[/] "
                "once and complete the wizard - the dashboard manages that brain."
            )
            return 1
        # LITE feature: bound to 127.0.0.1 only, no tool execution, no network
        return run_dashboard(console)

    dry_run = "--dry-run" in argv
    voice_requested = "--voice" in argv
    live_requested = "--live" in argv
    cfg = config.Config.load()
    if cfg is None:
        cfg = run_wizard(console)
    # Mark XVII: quiet background update check (opt-out via settings)
    if cfg.updates.check_on_start:
        threading.Thread(
            target=_startup_update_check, args=(cfg, console), daemon=True
        ).start()
    _chat_loop(
        cfg, console, dry_run=dry_run, voice_requested=voice_requested,
        live_requested=live_requested,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
