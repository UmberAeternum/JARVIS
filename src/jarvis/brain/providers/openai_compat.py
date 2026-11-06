"""Brain v0 - the OpenAI-compatible adapter: composes the legacy Brain.

The existing jarvis.Brain already speaks the OpenAI-compatible protocol with
failover via BrainChain; this adapter adapts that proven machinery to the
new Provider interface instead of reimplementing it.
"""

from __future__ import annotations

from .base import Provider


class OpenAICompatProvider(Provider):
    name = "openai-compat"

    def __init__(self, brain, embed=None, vision: bool = False):
        # brain: a jarvis.Brain (proven chat path). embed/vision are
        # capability flags supplied by the manifest, not guesses.
        self._brain = brain
        self._embed = embed
        self._vision = vision

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        kwargs = dict(model=self._brain.model, messages=messages)
        if tools:
            kwargs["tools"] = tools
        response = self._brain.client().chat.completions.create(**kwargs)
        message = response.choices[0].message
        tool_calls = None
        raw_calls = getattr(message, "tool_calls", None)
        if raw_calls:
            tool_calls = [
                {"id": call.id, "name": call.function.name,
                 "arguments": call.function.arguments}
                for call in raw_calls
            ]
        return {"reply": (message.content or "").strip(), "tool_calls": tool_calls}

    def tools(self) -> list[str]:
        return []  # server-side tool execution is not an OpenAI-compat feature

    def vision(self) -> bool:
        return self._vision

    def embed(self, text: str) -> list[float] | None:
        return self._embed(text) if self._embed else None

    def health(self) -> dict:
        from .. import validate_brain

        ok, detail = validate_brain(self._brain)
        return {"ok": ok, "detail": detail}
