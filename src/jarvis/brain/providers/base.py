"""Brain v0 - the provider abstraction: one interface, many backends.

Every adapter implements the same surface (chat, stream, tools, vision,
embed, health) so the router can treat models interchangeably. Adapters
NEVER execute tools and NEVER see grant state - they only talk to models;
the policy spine (access.authorize) decides what may run.
"""

from __future__ import annotations


class Provider:
    """Abstract brain provider. All methods return plain dictionaries."""

    name: str = "abstract"

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """One chat turn. Returns a dictionary holding the reply text and,
        when the model proposed them, tool call objects."""
        raise NotImplementedError

    def stream(self, messages: list[dict], on_text_delta) -> dict:
        """Streaming chat; adapters without streaming delegate to chat."""
        return self.chat(messages)

    def tools(self) -> list[str]:
        """Tool names this provider or server can run (empty when none)."""
        return []

    def vision(self) -> bool:
        """Whether this provider accepts image inputs."""
        return False

    def embed(self, text: str) -> list[float] | None:
        """Embedding vector, or None when unsupported."""
        return None

    def health(self) -> dict:
        """Cheap reachability probe: a dictionary with an ok flag."""
        raise NotImplementedError

    def capabilities(self) -> dict:
        """Introspection: name, tool support, vision, embed, health."""
        return {
            "name": self.name,
            "tools": self.tools(),
            "vision": self.vision(),
            "embed": self.embed("probe") is not None,
            "health_ok": bool(self.health().get("ok")),
        }
