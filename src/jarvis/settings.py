"""Mark XVI - settings management: show (redacted), set, reset.

Secrets are never printed: API keys are masked via config.mask_key and the
license key never appears at all (only the tier, via jarvis license status).
`set` accepts a strict whitelist of dotted keys - anything outside it is
refused rather than guessed at.
"""

from __future__ import annotations

from . import config
from .config import BrainConfig, mask_key

SETTABLE: tuple[str, ...] = (
    "brains.primary.type",
    "brains.primary.provider",
    "brains.primary.base_url",
    "brains.primary.model",
    "brains.primary.api_key",
    "brains.fallback.type",
    "brains.fallback.provider",
    "brains.fallback.base_url",
    "brains.fallback.model",
    "brains.fallback.api_key",
    "voice.enabled",
    "voice.stt_model",
    "voice.tts_enabled",
    "voice.mic_device",
    "voice.profile",
    "voice.stt_provider",
    "voice.tts_provider",
    "voice.cloud_stt",
    "voice.cloud_tts",
    "voice.cloud_stt_url",
    "voice.cloud_tts_url",
    "vision.enabled",
    "vision.model",
    "vision.auto_attach",
    "vision.interval_s",
    "vision.max_width",
    "vision.monitor",
    "vision.screen_control",
    "updates.check_on_start",
    "updates.manifest_url",
    "diagnostics.crash_reports",
    "ambient.nudges",
    "ambient.battery",
    "ambient.reminders",
    "ambient.health",
    "ambient.quiet_start",
    "ambient.quiet_end",
    "ambient.rate_limit_min",
    "hud.theme",
    "hud.sound",
    "hud.typed",
    "hud.boot",
    "hud.reduced_motion",
    "gestures.enabled",
    "gestures.idle_timeout_s",
    "gestures.threshold",
    "router.max_cost_per_request",
    "router.daily_budget",
    "max_tool_iterations",
    "max_tokens_per_turn",
    "use_keyring",
)


def apply_setting(cfg: config.Config, dotted: str, value: str) -> str:
    """Apply one dotted setting to cfg and return a human confirmation.

    Raises KeyError for unknown settings and ValueError for bad values.
    The confirmation line for secrets shows a mask, never the value.
    """
    if dotted not in SETTABLE:
        raise KeyError(dotted)
    if dotted.startswith("brains.fallback.") and cfg.brains.fallback is None:
        cfg.brains.fallback = BrainConfig(type="cloud", provider="custom")
    target: object = cfg
    parts = dotted.split(".")
    for part in parts[:-1]:
        target = getattr(target, part)
    attr = parts[-1]
    current = getattr(target, attr)
    if isinstance(current, bool):
        parsed: object = value.strip().lower() in ("1", "true", "yes", "on")
    elif isinstance(current, int):
        try:
            parsed = int(value)
        except ValueError:
            raise ValueError(f"{dotted} needs an integer, got {value!r}") from None
    elif current is None:  # voice.mic_device: int or null
        text = value.strip().lower()
        if text in ("", "none", "default"):
            parsed = None
        else:
            try:
                parsed = int(text)
            except ValueError:
                raise ValueError(f"{dotted} needs an integer or 'none', got {value!r}") from None
    else:
        parsed = value
    setattr(target, attr, parsed)
    if dotted.endswith("api_key"):
        return f"{dotted} updated (stored - shown as {mask_key(str(parsed))})"
    return f"{dotted} = {parsed}"


def show_text(cfg: config.Config) -> str:
    """Redacted settings dump - safe to print, paste, or attach to a report."""
    primary = cfg.brains.primary
    key = primary.api_key or config.load_key("primary") or ""
    lines = [
        f"brain.primary: {primary.type} / {primary.provider} / {primary.model}"
        f" @ {primary.base_url or '(provider preset)'}",
        f"  api key: {mask_key(key)}",
    ]
    fallback = cfg.brains.fallback
    if fallback is not None:
        fb_key = fallback.api_key or config.load_key("fallback") or ""
        lines.append(
            f"brain.fallback: {fallback.type} / {fallback.provider} / {fallback.model}"
            f" @ {fallback.base_url or '(provider preset)'}"
        )
        lines.append(f"  api key: {mask_key(fb_key)}")
    else:
        lines.append("brain.fallback: (none)")
    lines.append(f"keyring storage: {'on' if cfg.use_keyring else 'off'}")
    lines.append(
        f"tool budget: {cfg.max_tool_iterations} iterations / "
        f"{cfg.max_tokens_per_turn} tokens per turn"
    )
    lines.append(
        f"voice: enabled={cfg.voice.enabled} tts={cfg.voice.tts_enabled} "
        f"stt_model={cfg.voice.stt_model} profile={cfg.voice.profile or '(system default)'}"
    )
    lines.append(
        f"vision: enabled={cfg.vision.enabled} monitor={cfg.vision.monitor} "
        f"screen_control={cfg.vision.screen_control} max_width={cfg.vision.max_width}"
    )
    lines.append(
        f"updates: check_on_start={cfg.updates.check_on_start}"
        + (f" manifest_url={cfg.updates.manifest_url}" if cfg.updates.manifest_url else "")
    )
    lines.append(f"diagnostics: crash_reports={cfg.diagnostics.crash_reports}")
    lines.append(
        f"ambient: nudges={cfg.ambient.nudges} battery={cfg.ambient.battery} "
        f"reminders={cfg.ambient.reminders} health={cfg.ambient.health} "
        f"quiet={cfg.ambient.quiet_start}-{cfg.ambient.quiet_end} "
        f"rate_limit_min={cfg.ambient.rate_limit_min}"
    )
    lines.append(
        f"hud: theme={cfg.hud.theme} sound={cfg.hud.sound} typed={cfg.hud.typed} "
        f"boot={cfg.hud.boot}"
    )
    lines.append(f"config file: {config.config_path()}")
    return "\n".join(lines)


def reset_config() -> str:
    """Remove the configuration file. Memories, health data and the license
    key are intentionally kept - this resets the brain/settings only."""
    path = config.config_path()
    if not path.exists():
        return "Nothing to reset - no configuration file exists."
    path.unlink()
    return (
        f"Configuration removed ({path}). Run [bold]jarvis setup[/] to configure "
        "a new brain. Memories, health data and your license are kept."
    )
