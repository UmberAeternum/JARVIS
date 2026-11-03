"""Per-user configuration (schema v3), stored in the OS user-config directory.

Key material never belongs in the repository. By default the API key lives in
config.json inside the user's own profile; optionally it is stored in the OS
keychain via the 'keyring' package (pip install jarvis-ai[secure]), in which
case the JSON keeps only metadata. The key is never printed to the console.

v3 adds the voice layer (Mark II): push-to-talk capture, STT, TTS.
v4 adds the vision layer (Mark III): screen capture, live-attach, watch mode.
Older configs migrate automatically on load.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "jarvis"
KEYRING_SERVICE = "jarvis"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


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
class Config:
    version: int = 4
    brains: BrainsConfig = field(default_factory=BrainsConfig)
    use_keyring: bool = False
    max_tool_iterations: int = 8
    max_tokens_per_turn: int = 100_000
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
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
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )

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
