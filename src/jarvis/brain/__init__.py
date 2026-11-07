"""Provider-agnostic LLM clients - JARVIS's brain (now the Brain package).

Every supported brain speaks the OpenAI-compatible chat-completions API, so a
single client covers cloud providers and local servers alike. On top of a
single Brain sits BrainChain: a primary brain with an optional fallback that
takes over when the primary is offline or rate-limited (circuit-breaker
behavior; the switch is sticky for the session and reported to the user).

URL policy: all outbound HTTP goes through safety.guarded_fetch_json, which
enforces the SSRF rule (http/https only, host + resolved-IP boundary checks,
no redirects). Local brain endpoints are the explicit, sanctioned exception
(allow_local=True); no model-influenced URL ever reaches a fetch.

Brain v0 (the router era): this package now also hosts the provider
abstraction (providers/), capability manifests (manifest.py), the single
gateway complete(), and error classification - see the submodules. The
legacy names below are unchanged; every existing import keeps working.
"""

from __future__ import annotations

import os
import socket
import types
from dataclasses import dataclass
from typing import Callable

from .. import safety  # jarvis.safety - one level up from the brain package
from ..config import BrainConfig

check_url = safety.check_url  # single URL validator for the whole project

# Presets: defaults only. The user's key is validated live before it is saved.
PROVIDERS: dict[str, dict] = {
    "zai": {
        "label": "Z.AI (GLM)",
        "base_url": "https://api.z.ai/api/paas/v4",
        "model": "glm-4.6",
        "key_url": "https://z.ai/manage-apikey/apikey-list",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "key_url": "https://platform.openai.com/api-keys",
    },
    "zhipu": {
        "label": "Zhipu AI (GLM, mainland China)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
    },
    "gemini": {
        "label": "Google Gemini (OpenAI-compatible endpoint)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "key_url": "https://aistudio.google.com/app/apikey",
    },
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "model": "",
        "key_url": None,
    },
    "custom": {
        "label": "Custom (any OpenAI-compatible server)",
        "base_url": "",
        "model": "",
        "key_url": None,
    },
}

VALIDATION_PROMPT = "ping"

# Name heuristics for non-chat models (embedding/audio/vision encoders), used
# to filter discovery results down to models that can actually carry a
# tool-calling conversation.
NON_CHAT_MARKERS = (
    "embed",
    "bge-",
    "minilm",
    "e5-",
    "rerank",
    "whisper",
    "clip",
    "llava",  # vision encoder - chat-capable but not a tool-calling pick
)


def is_chat_model(name: str) -> bool:
    lowered = name.lower()
    return not any(marker in lowered for marker in NON_CHAT_MARKERS)


@dataclass
class Brain:
    """A configured chat-completions endpoint."""

    base_url: str
    model: str
    api_key: str

    @classmethod
    def from_config(cls, brain_cfg: BrainConfig) -> "Brain":
        key = os.environ.get("JARVIS_API_KEY") or brain_cfg.api_key
        return cls(base_url=brain_cfg.base_url, model=brain_cfg.model, api_key=key)

    def client(self):
        from openai import OpenAI  # imported lazily so --version never pays for it

        return OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=120.0)


def validate_brain(brain: Brain) -> tuple[bool, str]:
    """Prove the endpoint is policy-clean, then one tiny live call to prove
    endpoint + key + model work. The endpoint guard runs BEFORE any network
    traffic: private/reserved addresses (e.g. the cloud-metadata endpoint
    169.254.169.254) are refused without a single packet leaving."""
    ok, reason = safety.check_brain_endpoint(brain.base_url)
    if not ok:
        return False, f"endpoint rejected: {reason}"
    try:
        client = brain.client()
        resp = client.chat.completions.create(
            model=brain.model,
            messages=[{"role": "user", "content": VALIDATION_PROMPT}],
            max_tokens=8,
        )
        text = (resp.choices[0].message.content or "").strip()
        return True, f"OK - model replied: {text[:40]!r}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ------------------------------------------------------------------ chain


def _is_transient(exc: Exception) -> bool:
    """Connection failures and rate limits are worth a fallback attempt."""
    try:
        from openai import APIConnectionError, APIStatusError
    except ImportError:  # pragma: no cover
        return False
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) in (
        429, 500, 502, 503, 504,
    ):
        return True
    return False


def classify_error(exc: Exception) -> str:
    """Brain v0: error classification for the fallback chain - one name per
    failure family, so routing decisions can be made on the class."""
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    try:
        from openai import APIConnectionError, APIStatusError, AuthenticationError

        if isinstance(exc, AuthenticationError):
            return "auth"
        if isinstance(exc, APIConnectionError):
            return "connection"
        if isinstance(exc, APIStatusError):
            code = getattr(exc, "status_code", None)
            if code == 429:
                return "rate_limit"
            if code in (500, 502, 503, 504):
                return "server"
    except ImportError:
        pass
    return "unknown"


class BrainChain:
    """Primary brain with an optional fallback; failover is sticky per session."""

    def __init__(
        self,
        primary: Brain,
        fallback: Brain | None = None,
        on_status: Callable[[str], None] | None = None,
        transient_check: Callable[[Exception], bool] | None = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.on_status = on_status or (lambda status: None)
        self._transient = transient_check or _is_transient
        self.active = primary

    def create_chat(self, messages: list[dict], tools: list[dict] | None = None,
                    tool_choice: str = "auto"):
        try:
            return self._call(self.active, messages, tools, tool_choice)
        except Exception as exc:
            if self.fallback is not None and self.active is self.primary and self._transient(exc):
                self.on_status(
                    f"primary brain unavailable ({type(exc).__name__}) - "
                    f"switching to fallback model {self.fallback.model}"
                )
                self.active = self.fallback
                return self._call(self.fallback, messages, tools, tool_choice)
            raise

    def create_chat_stream(self, messages: list[dict], tools: list[dict] | None = None,
                           tool_choice: str = "auto",
                           on_text_delta: Callable[[str], None] | None = None):
        """Streaming variant: forwards reply text to on_text_delta as it
        arrives and returns the same shape as create_chat. Falls back to the
        non-streaming path when the provider rejects streaming."""
        try:
            stream = self._call(self.active, messages, tools, tool_choice, stream=True)
        except Exception:
            return self.create_chat(messages, tools, tool_choice)
        content: list[str] = []
        tool_acc: dict[int, dict] = {}
        usage = None
        try:
            for chunk in stream:
                usage = getattr(chunk, "usage", None) or usage
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    content.append(text)
                    if on_text_delta is not None:
                        on_text_delta(text)
                for piece in (getattr(delta, "tool_calls", None) or []):
                    slot = tool_acc.setdefault(
                        piece.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if getattr(piece, "id", None):
                        slot["id"] = piece.id
                    function = getattr(piece, "function", None)
                    if function is not None:
                        if function.name:
                            slot["name"] = function.name
                        if function.arguments:
                            slot["arguments"] += function.arguments
        except Exception:
            return self.create_chat(messages, tools, tool_choice)  # mid-stream failure
        tool_calls = [
            _StreamedToolCall(slot["id"], slot["name"], slot["arguments"])
            for slot in tool_acc.values()
            if slot["name"]
        ]
        message = types.SimpleNamespace(
            content="".join(content) or None, tool_calls=tool_calls or None
        )
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice], usage=usage)

    def _call(self, brain: Brain, messages: list[dict], tools: list[dict] | None,
              tool_choice: str, stream: bool = False):
        kwargs = dict(
            model=brain.model,
            messages=messages,
            tool_choice=tool_choice,
        )
        if tools:
            kwargs["tools"] = tools
        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
        return brain.client().chat.completions.create(**kwargs)


class _StreamedToolCall:
    """Tool call aggregated from stream deltas; mimics the SDK shape."""

    def __init__(self, call_id: str, name: str, arguments: str):
        self.id = call_id
        self.function = types.SimpleNamespace(name=name, arguments=arguments)

    def model_dump(self) -> dict:
        return {
            "id": self.id,
            "function": {"name": self.function.name, "arguments": self.arguments},
        }


def make_brain_chain(cfg, on_status: Callable[[str], None] | None = None) -> BrainChain:
    """Build a BrainChain from a Config (primary + optional fallback)."""
    primary = Brain.from_config(cfg.brains.primary)
    fallback = Brain.from_config(cfg.brains.fallback) if cfg.brains.fallback else None
    return BrainChain(primary, fallback, on_status=on_status)


# ------------------------------------------------------- local discovery


def list_ollama_models(base_url: str = "http://localhost:11434", chat_only: bool = True) -> list[str]:
    """List chat-capable models installed in a local Ollama server ([] if unreachable)."""
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    try:
        data = safety.guarded_fetch_json(f"{base}/api/tags", allow_local=True)
    except (ValueError, OSError):
        return []
    names = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    return sorted(n for n in names if is_chat_model(n) or not chat_only)


def list_lmstudio_models(base_url: str = "http://localhost:1234", chat_only: bool = True) -> list[str]:
    """List chat-capable models loaded in a local LM Studio server ([] if unreachable)."""
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    try:
        data = safety.guarded_fetch_json(f"{base}/models", allow_local=True)
    except (ValueError, OSError):
        return []
    names = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    return sorted(n for n in names if is_chat_model(n) or not chat_only)


def discover_local_servers() -> list[dict]:
    """Probe known local servers; return [{id, label, base_url, models}] (non-empty only)."""
    found: list[dict] = []
    ollama = list_ollama_models()
    if ollama:
        found.append(
            {
                "id": "ollama",
                "label": "Ollama (localhost:11434)",
                "base_url": "http://localhost:11434/v1",
                "models": ollama,
            }
        )
    lmstudio = list_lmstudio_models()
    if lmstudio:
        found.append(
            {
                "id": "lmstudio",
                "label": "LM Studio (localhost:1234)",
                "base_url": "http://localhost:1234/v1",
                "models": lmstudio,
            }
        )
    return found


# ------------------------------------------------------- gateway (Brain v0)


def complete(request: dict, cfg=None, on_status: Callable[[str], None] | None = None) -> dict:
    """The single gateway (Brain v0): one internal entry every UMBRA surface
    can call. Behavior-preserving by construction - it drives the same
    BrainChain machinery the surfaces use today.

    request: {"text": "..."} or {"messages": [...]} plus optional "tools".
    Returns {"reply": str, "route": {...}} - the route block records which
    brain answered and whether failover fired (metadata only, no prompt).
    """
    cfg = cfg or config.Config.load() or config.Config()
    chain = make_brain_chain(cfg, on_status=on_status)
    if "messages" in request:
        messages = request["messages"]
    else:
        messages = [{"role": "user", "content": str(request.get("text", ""))}]
    tools = request.get("tools")
    response = chain.create_chat(messages=messages, tools=tools)
    reply = (response.choices[0].message.content or "").strip()
    return {
        "reply": reply,
        "route": {
            "model": chain.active.model,
            "base_url": chain.active.base_url,
            "fallback_active": chain.active is not chain.primary,
            "provider": "brain-chain",
        },
    }


# re-export the config shim some legacy callers relied on via brain.Config
from .. import config as config  # noqa: E402,F401 - re-export for compatibility
