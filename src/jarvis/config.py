"""Per-user configuration (schema v4), stored in the OS user-config directory.

Key material never belongs in the repository. By default the API key lives in
config.json inside the user's own profile; optionally it is stored in the OS
keychain via the 'keyring' package (pip install jarvis-ai[secure]), in which
case the JSON keeps only metadata. The key is never printed to the console.

v3 adds the voice layer (Mark II): push-to-talk capture, STT, TTS.
v4 adds the vision layer (Mark III): screen capture, live-attach, watch mode.
Mark XVII/XVIII add the updates and diagnostics sections additively.
Mark XIX adds profiles: the base directory IS the "default" profile (existing
data stays put); other profiles live at <base>/profiles/<name>/ and every
module picks them up because all of them resolve config.config_dir() here,
dynamically. Older configs migrate automatically on load.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "jarvis"
KEYRING_SERVICE = "jarvis"
DEFAULT_PROFILE = "default"

_profile_override: str | None = None  # set by using_profile()


def _base_dir() -> Path:
    """The physical root: the original single-profile directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def active_profile() -> str:
    """The recorded active profile; "default" when unset."""
    if _profile_override is not None:
        return _profile_override
    marker = _base_dir() / "profile"
    try:
        name = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_PROFILE
    return name or DEFAULT_PROFILE


def set_active_profile(name: str) -> None:
    """Record the active profile. "default" removes the marker file."""
    marker = _base_dir() / "profile"
    if name == DEFAULT_PROFILE:
        try:
            marker.unlink()
        except OSError:
            pass
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(name, encoding="utf-8")


@contextmanager
def using_profile(name: str):
    """Temporarily resolve config_dir() to the named profile (export/import, tests)."""
    global _profile_override
    previous = _profile_override
    _profile_override = name
    try:
        yield
    finally:
        _profile_override = previous


def config_dir() -> Path:
    """Directory of the ACTIVE profile: the base dir itself for "default"
    (so existing data is the default profile - nothing migrates), otherwise
    <base>/profiles/<name>."""
    name = active_profile()
    if name == DEFAULT_PROFILE:
        return _base_dir()
    return _base_dir() / "profiles" / name


def config_path() -> Path:
    return config_dir() / "config.json"


# --------------------------------------------------------------------- keyring


def keyring_available() -> bool:
    try:
        import keyring  # noqa: F401 - availability probe only
    except ImportError:
        return False
    return True


def store_key(account: str, value: str) -> bool:
    """Store a secret in the OS keychain. Returns False when unavailable."""
    if not value:
        return False
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, account, value)
        return True
    except Exception:
        return False


def load_key(account: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, account)
    except Exception:
        return None


# -------------------------------------------------------------------- schema


@dataclass
class BrainConfig:
    type: str = "cloud"          # "cloud" | "local"
    provider: str = "zai"        # preset id, see brain.PROVIDERS
    base_url: str = ""
    model: str = ""
    api_key: str = ""


@dataclass
class BrainsConfig:
    primary: BrainConfig = field(default_factory=BrainConfig)
    fallback: BrainConfig | None = None  # used when the primary is offline/rate-limited


@dataclass
class VoiceConfig:
    enabled: bool = False        # push-to-talk capture active?
    stt_model: str = "base"      # faster-whisper model size (tiny/base/small/...)
    tts_enabled: bool = True     # speak replies aloud?
    mic_device: int | None = None  # sounddevice input device index (None = default)
    wake_phrase: str = "Hey UMBRA"  # Mark XXVIII: hands-free wake phrase
    profile: str = ""            # Mark XXIX: "" | "jarvis" (British butler TTS)
    # Phase 12 - the streaming provider layer. Local first; cloud is opt-in
    # twice (provider=cloud AND cloud_*), stated in settings show / wizard.
    stt_provider: str = "local"  # "local" | "cloud"
    tts_provider: str = "local"  # "local" | "cloud"
    cloud_stt: bool = False      # explicit audio-leaves-machine consent (STT)
    cloud_tts: bool = False      # explicit text-leaves-machine consent (TTS)
    cloud_stt_url: str = ""      # OpenAI-compatible endpoint; "" = brain base_url
    cloud_tts_url: str = ""      # OpenAI-compatible endpoint; "" = brain base_url


@dataclass
class HudConfig:
    """Mark XXIX: dashboard HUD polish. Pure presentation; defaults are the
    hologram look with sound + typed responses on."""

    theme: str = "hologram"      # hologram | minimal | hud | scanline (CSS only, no projection)
    sound: bool = True           # subtle sound cues (WebAudio, local)
    typed: bool = True           # typed-out response effect
    boot: bool = True            # boot sequence on dashboard load
    reduced_motion: bool = False  # phase 11: freeze orb animation (a11y override)


@dataclass
class VisionConfig:
    enabled: bool = False        # /live auto-attach active?
    model: str = ""              # vision-capable model id; "" = use the primary model
    auto_attach: bool = False    # remembered preference for live-attach
    interval_s: int = 20         # watch mode polling interval
    max_width: int = 1280        # captured frames are downscaled to this width
    monitor: int = 0             # 0 = primary display, 1 = second, ...
    screen_control: bool = False  # enable the screen_click/type/press/scroll tools


@dataclass
class UpdatesConfig:
    """Mark XVII: the update checker. The background check is opt-out."""

    check_on_start: bool = True
    manifest_url: str = ""  # empty = the default signed-manifest URL


@dataclass
class DiagnosticsConfig:
    """Mark XVIII: local support tooling. Crash reporting is opt-in."""

    crash_reports: bool = False  # write a local crash file on unhandled errors


@dataclass
class AccessConfig:
    """Mark XXXI: EDITH-protocol grant window. The grant itself is never
    settable here - only its expiry window is configurable."""

    window_hours: int = 24  # full access auto-revokes after this many hours


@dataclass
class RouterConfig:
    """Brain v1: the privacy router. Cloud providers are opt-in per
    provider; the budgets are hard stops, not advisories."""

    cloud_providers: list[str] = field(default_factory=list)  # opted-in provider ids
    max_cost_per_request: float = 0.05
    daily_budget: float = 0.50


@dataclass
class AmbientConfig:
    """Mark XXVIII: proactive nudges. Strictly opt-in, rate-limited, quiet
    hours respected; per-signal toggles (battery/reminders/health)."""

    nudges: bool = False         # master switch - default OFF
    battery: bool = True         # low-battery nudge
    reminders: bool = True       # due-reminders nudge
    health: bool = False         # health-band-shift nudge
    quiet_start: str = "23:00"   # quiet hours (may cross midnight)
    quiet_end: str = "07:00"
    rate_limit_min: int = 5      # at most one nudge per window


@dataclass
class GesturesConfig:
    """Phase 13: hand gestures. Opt-in, HUD-only control; the camera runs in
    the browser and never leaves the device. threshold scales the pinch
    distance (calibration, `jarvis gestures calibrate`)."""

    enabled: bool = False         # explicit toggle; default OFF
    idle_timeout_s: int = 30      # camera auto-off after no hand is seen
    threshold: float = 1.0        # pinch sensitivity multiplier


@dataclass
class Config:
    version: int = 4
    brains: BrainsConfig = field(default_factory=BrainsConfig)
    use_keyring: bool = False
    max_tool_iterations: int = 8
    max_tokens_per_turn: int = 100_000
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    updates: UpdatesConfig = field(default_factory=UpdatesConfig)
    diagnostics: DiagnosticsConfig = field(default_factory=DiagnosticsConfig)
    ambient: AmbientConfig = field(default_factory=AmbientConfig)
    gestures: GesturesConfig = field(default_factory=GesturesConfig)
    hud: HudConfig = field(default_factory=HudConfig)
    access: AccessConfig = field(default_factory=AccessConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    created_at: str = ""
    updated_at: str = ""

    # ------------------------------------------------------------------ save

    def to_dict(self) -> dict:
        keyring_active = self.use_keyring and keyring_available()

        def brain_dict(brain: BrainConfig | None, account: str) -> dict | None:
            if brain is None:
                return None
            api_key = brain.api_key
            if keyring_active and api_key:
                store_key(account, api_key)
                api_key = ""  # the JSON keeps metadata only
            return {
                "type": brain.type,
                "provider": brain.provider,
                "base_url": brain.base_url,
                "model": brain.model,
                "api_key": api_key,
            }

        return {
            "version": self.version,
            "brains": {
                "primary": brain_dict(self.brains.primary, "primary"),
                "fallback": brain_dict(self.brains.fallback, "fallback"),
            },
            "use_keyring": self.use_keyring,
            "max_tool_iterations": self.max_tool_iterations,
            "max_tokens_per_turn": self.max_tokens_per_turn,
            "voice": {
                "enabled": self.voice.enabled,
                "stt_model": self.voice.stt_model,
                "tts_enabled": self.voice.tts_enabled,
                "mic_device": self.voice.mic_device,
                "wake_phrase": self.voice.wake_phrase,
                "profile": self.voice.profile,
                "stt_provider": self.voice.stt_provider,
                "tts_provider": self.voice.tts_provider,
                "cloud_stt": self.voice.cloud_stt,
                "cloud_tts": self.voice.cloud_tts,
                "cloud_stt_url": self.voice.cloud_stt_url,
                "cloud_tts_url": self.voice.cloud_tts_url,
            },
            "vision": {
                "enabled": self.vision.enabled,
                "model": self.vision.model,
                "auto_attach": self.vision.auto_attach,
                "interval_s": self.vision.interval_s,
                "max_width": self.vision.max_width,
                "monitor": self.vision.monitor,
                "screen_control": self.vision.screen_control,
            },
            "updates": {
                "check_on_start": self.updates.check_on_start,
                "manifest_url": self.updates.manifest_url,
            },
            "diagnostics": {
                "crash_reports": self.diagnostics.crash_reports,
            },
            "ambient": {
                "nudges": self.ambient.nudges,
                "battery": self.ambient.battery,
                "reminders": self.ambient.reminders,
                "health": self.ambient.health,
                "quiet_start": self.ambient.quiet_start,
                "quiet_end": self.ambient.quiet_end,
                "rate_limit_min": self.ambient.rate_limit_min,
            },
            "hud": {
                "theme": self.hud.theme,
                "sound": self.hud.sound,
                "typed": self.hud.typed,
                "boot": self.hud.boot,
                "reduced_motion": self.hud.reduced_motion,
            },
            "gestures": {
                "enabled": self.gestures.enabled,
                "idle_timeout_s": self.gestures.idle_timeout_s,
                "threshold": self.gestures.threshold,
            },
            "access": {
                "window_hours": self.access.window_hours,
            },
            "router": {
                "cloud_providers": self.router.cloud_providers,
                "max_cost_per_request": self.router.max_cost_per_request,
                "daily_budget": self.router.daily_budget,
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def save(self) -> Path:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self.created_at:
            self.created_at = now
        self.updated_at = now
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        if sys.platform != "win32":
            try:
                path.chmod(0o600)  # best-effort: only the owner may read it
            except OSError:
                pass
        return path

    # ------------------------------------------------------------------ load

    @classmethod
    def load(cls) -> "Config | None":
        """Return the saved config, or None when absent/corrupt (triggers the wizard)."""
        path = config_path()
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            version = int(raw.get("version", 1))
            if version < 2:
                return cls._from_v1(raw)
            return cls._from_modern(raw)
        except (json.JSONDecodeError, TypeError, OSError, ValueError):
            return None

    @classmethod
    def _brain_from(cls, raw: dict | None, account: str, use_keyring: bool) -> BrainConfig | None:
        if raw is None:
            return None
        known = {f.name for f in fields(BrainConfig)}
        brain = BrainConfig(**{k: v for k, v in raw.items() if k in known})
        if use_keyring and not brain.api_key:
            brain.api_key = load_key(account) or ""
        return brain

    @classmethod
    def _brains_from(cls, raw: dict, use_keyring: bool) -> BrainsConfig:
        brains_raw = raw.get("brains", {})
        return BrainsConfig(
            primary=cls._brain_from(brains_raw.get("primary", {}), "primary", use_keyring)
            or BrainConfig(),
            fallback=cls._brain_from(brains_raw.get("fallback"), "fallback", use_keyring),
        )

    @classmethod
    def _voice_from(cls, raw: dict | None) -> VoiceConfig:
        known = {f.name for f in fields(VoiceConfig)}
        return VoiceConfig(**{k: v for k, v in (raw or {}).items() if k in known})

    @classmethod
    def _vision_from(cls, raw: dict | None) -> VisionConfig:
        known = {f.name for f in fields(VisionConfig)}
        return VisionConfig(**{k: v for k, v in (raw or {}).items() if k in known})

    @classmethod
    def _updates_from(cls, raw: dict | None) -> UpdatesConfig:
        known = {f.name for f in fields(UpdatesConfig)}
        return UpdatesConfig(**{k: v for k, v in (raw or {}).items() if k in known})

    @classmethod
    def _diagnostics_from(cls, raw: dict | None) -> DiagnosticsConfig:
        known = {f.name for f in fields(DiagnosticsConfig)}
        return DiagnosticsConfig(**{k: v for k, v in (raw or {}).items() if k in known})

    @classmethod
    def _ambient_from(cls, raw: dict | None) -> AmbientConfig:
        known = {f.name for f in fields(AmbientConfig)}
        return AmbientConfig(**{k: v for k, v in (raw or {}).items() if k in known})

    @classmethod
    def _hud_from(cls, raw: dict | None) -> HudConfig:
        known = {f.name for f in fields(HudConfig)}
        return HudConfig(**{k: v for k, v in (raw or {}).items() if k in known})

    @classmethod
    def _access_from(cls, raw: dict | None) -> AccessConfig:
        known = {f.name for f in fields(AccessConfig)}
        return AccessConfig(**{k: v for k, v in (raw or {}).items() if k in known})

    @classmethod
    def _router_from(cls, raw: dict | None) -> RouterConfig:
        known = {f.name for f in fields(RouterConfig)}
        cloud = raw.get("cloud_providers") if raw else None
        values = {k: v for k, v in (raw or {}).items() if k in known and k != "cloud_providers"}
        cfg = RouterConfig(**values)
        if isinstance(cloud, list):
            cfg.cloud_providers = [str(item) for item in cloud]
        return cfg

    @classmethod
    def _from_modern(cls, raw: dict) -> "Config":
        """v2/v3/v4 share every key except voice and vision (defaults fill in)."""
        use_keyring = bool(raw.get("use_keyring", False))
        return cls(
            version=4,
            brains=cls._brains_from(raw, use_keyring),
            use_keyring=use_keyring,
            max_tool_iterations=int(raw.get("max_tool_iterations", 8)),
            max_tokens_per_turn=int(raw.get("max_tokens_per_turn", 100_000)),
            voice=cls._voice_from(raw.get("voice")),
            vision=cls._vision_from(raw.get("vision")),
            updates=cls._updates_from(raw.get("updates")),
            diagnostics=cls._diagnostics_from(raw.get("diagnostics")),
            ambient=cls._ambient_from(raw.get("ambient")),
            hud=cls._hud_from(raw.get("hud")),
            gestures=cls._gestures_from(raw.get("gestures")),
            access=cls._access_from(raw.get("access")),
            router=cls._router_from(raw.get("router")),
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )

    @classmethod
    def _gestures_from(cls, raw: dict | None) -> GesturesConfig:
        known = {f.name for f in fields(GesturesConfig)}
        return GesturesConfig(**{k: v for k, v in (raw or {}).items() if k in known})

    @classmethod
    def _from_v1(cls, raw: dict) -> "Config":
        """Migrate a v0.1.0 config: the old single 'brain' becomes the primary."""
        known = {f.name for f in fields(BrainConfig)}
        primary = BrainConfig(**{k: v for k, v in raw.get("brain", {}).items() if k in known})
        return cls(
            version=4,
            brains=BrainsConfig(primary=primary, fallback=None),
            use_keyring=False,
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )


def mask_key(key: str) -> str:
    if not key:
        return "(none)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"
