"""First-run onboarding: cloud or local brain, optional fallback, keyring.

The key is captured with getpass (never echoed), validated with a real API
call before anything is persisted, then stored in the OS keychain (when the
keyring extra is installed and the user opts in) or in the user's config
file. The wizard can be re-run any time with /setup.
"""

from __future__ import annotations

from getpass import getpass

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from . import brain, config
from .config import BrainConfig, BrainsConfig, Config, mask_key

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

    cfg = Config(
        brains=BrainsConfig(primary=primary, fallback=fallback),
        use_keyring=use_keyring,
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
    return cfg
