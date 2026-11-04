"""First-run onboarding: cloud or local brain, optional fallback, keyring.

The key is captured with getpass (never echoed), validated with a real API
call before anything is persisted, then stored in the OS keychain (when the
keyring extra is installed and the user opts in) or in the user's config
file. The wizard can be re-run any time with /setup or `jarvis setup`.
`jarvis setup --yes` runs the same flow without prompts for CI (Mark XVI).
"""

from __future__ import annotations

import os
from getpass import getpass

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from . import brain, config
from .config import BrainConfig, BrainsConfig, Config, VoiceConfig, mask_key

WIZARD_TITLE = "[bold cyan]J.A.R.V.I.S. - setup[/]"


def _pick_provider(console: Console) -> str:
    console.print()
    for i, (pid, preset) in enumerate(brain.PROVIDERS.items(), start=1):
        console.print(f"  [bold]{i}.[/] {preset['label']}")
    choice = Prompt.ask(
        "Choose a brain provider",
        choices=[str(i) for i in range(1, len(brain.PROVIDERS) + 1)],
        default="1",
    )
    return list(brain.PROVIDERS)[int(choice) - 1]


def _setup_local(console: Console) -> BrainConfig:
    servers = brain.discover_local_servers()
    if servers:
        console.print("  [green]Local AI servers detected:[/]")
        for i, server in enumerate(servers, start=1):
            console.print(f"    [bold]{i}.[/] {server['label']}")
        choice = Prompt.ask(
            "Choose a server",
            choices=[str(i) for i in range(1, len(servers) + 1)],
            default="1",
        )
        server = servers[int(choice) - 1]
        models = server["models"]
        console.print(f"  Models on {server['label']} (chat-capable only):")
        for i, name in enumerate(models, start=1):
            console.print(f"    [bold]{i}.[/] {name}")
        pick = Prompt.ask(
            "Choose a model",
            choices=[str(i) for i in range(1, len(models) + 1)],
            default="1",
        )
        return BrainConfig(
            type="local",
            provider=server["id"],
            base_url=server["base_url"],
            model=models[int(pick) - 1],
            api_key="local",
        )
    console.print(
        "  [yellow]No local AI server found.[/]\n"
        "  Install Ollama from https://ollama.com, then pull a tool-capable model:\n"
        "    [bold]ollama pull qwen2.5:7b[/]\n"
        "  (or start LM Studio's local server) and run /setup again."
    )
    url = Prompt.ask("Local server URL (OpenAI-compatible)", default="http://localhost:11434/v1")
    model = Prompt.ask("Model id (typed manually)", default="qwen2.5:7b").strip()
    return BrainConfig(type="local", provider="custom-local", base_url=url, model=model,
                       api_key="local")


def _setup_cloud(console: Console) -> BrainConfig:
    provider = _pick_provider(console)
    preset = brain.PROVIDERS[provider]
    base_url = preset["base_url"]
    model = preset["model"]

    if provider == "custom":
        base_url = Prompt.ask("Base URL (OpenAI-compatible, e.g. https://host/v1)").strip()
    model = Prompt.ask("Model id", default=model or "model id").strip()

    cfg = BrainConfig(type="cloud", provider=provider, base_url=base_url, model=model)

    if preset.get("key_url"):
        console.print(f"  [dim]Get a key: {preset['key_url']}[/]")
    api_key = ""
    while True:
        if not api_key:
            api_key = getpass("API key (input hidden): ").strip()
            if not api_key:
                console.print("  [red]API key cannot be empty.[/]")
                continue
        ok, message = brain.validate_brain(brain.Brain(base_url, model, api_key))
        if ok:
            console.print(f"  [green]Key validated:[/] {message}")
            break
        console.print(f"  [red]Validation failed:[/] {message}")
        if not Confirm.ask("Try another key?", default=True):
            raise SystemExit("Setup aborted - no valid key configured.")
        api_key = ""  # re-prompt at the top of the loop; empty input is caught there
    cfg.api_key = api_key
    return cfg


def _setup_brain(console: Console, role: str) -> BrainConfig:
    console.print(f"\n[bold]{role.capitalize()} brain[/]")
    brain_type = Prompt.ask("Type", choices=["cloud", "local"], default="cloud")
    if brain_type == "local":
        return _setup_local(console)
    return _setup_cloud(console)


def run_wizard(console: Console) -> Config:
    console.print(Panel(WIZARD_TITLE, border_style="cyan"))

    use_keyring = False
    if config.keyring_available():
        use_keyring = Confirm.ask(
            "Store API key(s) in the OS keychain? (recommended)", default=True
        )

    primary = _setup_brain(console, "primary")
    fallback = None
    if Confirm.ask(
        "Configure a fallback brain? (takes over if the primary is offline or rate-limited)",
        default=False,
    ):
        fallback = _setup_brain(console, "fallback")

    voice_enabled = Confirm.ask(
        "Enable push-to-talk voice input? (needs the voice extra: pip install \"jarvis-ai[voice]\")",
        default=False,
    )
    tts_enabled = True
    if voice_enabled:
        tts_enabled = Confirm.ask("Speak replies aloud?", default=True)

    cfg = Config(
        brains=BrainsConfig(primary=primary, fallback=fallback),
        use_keyring=use_keyring,
        voice=VoiceConfig(enabled=voice_enabled, tts_enabled=tts_enabled),
    )
    path = cfg.save()
    key = primary.api_key or config.load_key("primary") or ""
    console.print(
        f"  [green]Config saved to[/] {path}\n"
        f"  primary: {primary.provider} ({primary.model})  key: {mask_key(key)}\n"
        + (
            f"  fallback: {fallback.provider} ({fallback.model})\n"
            if fallback
            else "  fallback: (none)\n"
        )
        + f"  key storage: {'OS keychain' if use_keyring and config.keyring_available() else 'config file'}"
    )

    # optional PRO activation right at the end of onboarding
    if Confirm.ask("Activate a PRO license key now?", default=False):
        from . import licensing

        lic_key = getpass("License key (input hidden): ").strip()
        if lic_key:
            ok, message = licensing.install_license(lic_key)
            style = "green" if ok else "red"
            console.print(f"  [{style}]{message}[/]")
    return cfg


def setup_noninteractive(args: list[str]) -> tuple[Config | None, str]:
    """jarvis setup --yes [--local] [--provider ID] [--model M]
                          [--base-url URL] [--api-key KEY]

    Never prompts. The API key comes from --api-key or the UMBRA_API_KEY
    environment variable (argv values can leak into process listings, so the
    env var is the recommended CI channel). Live key validation is skipped in
    this mode. Returns (config, message); config is None on failure. Messages
    never contain the key material.
    """
    def flag(name: str) -> str | None:
        if name in args:
            index = args.index(name)
            if index + 1 < len(args):
                return args[index + 1]
        return None

    provider = flag("--provider")
    model = flag("--model")
    base_url = flag("--base-url")
    api_key = flag("--api-key") or os.environ.get("UMBRA_API_KEY", "")

    if "--local" in args:
        primary = BrainConfig(
            type="local",
            provider=provider or "ollama",
            base_url=base_url or "http://localhost:11434/v1",
            model=model or "qwen2.5:7b",
            api_key="local",
        )
    else:
        if provider is None:
            return None, "--yes needs --provider <id> (or --local for Ollama)."
        if provider not in brain.PROVIDERS:
            return None, f"unknown provider: {provider} (known: {', '.join(brain.PROVIDERS)})"
        preset = brain.PROVIDERS[provider]
        if provider == "custom" and not base_url:
            return None, "provider 'custom' needs --base-url <url>."
        if not api_key:
            return None, "cloud setup needs an API key: pass --api-key or set UMBRA_API_KEY."
        primary = BrainConfig(
            type="cloud",
            provider=provider,
            base_url=base_url or preset["base_url"],
            model=model or preset["model"],
            api_key=api_key,
        )
    cfg = Config(brains=BrainsConfig(primary=primary), use_keyring=False)
    path = cfg.save()
    message = (
        f"Configuration written to {path}\n"
        f"  primary: {primary.provider} ({primary.model})  key: {mask_key(primary.api_key)}"
    )
    return cfg, message
