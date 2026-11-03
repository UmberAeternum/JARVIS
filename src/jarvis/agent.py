"""The agent turn loop: user request -> model -> tools -> results -> answer.

Runs until the model produces a final answer or a guardrail stops it. Two
guardrails bound every turn: a tool-iteration cap and a cumulative token
budget measured from response usage. History is trimmed from the middle
(system prompt and the current exchange stay; the oldest turns go first),
never splitting a tool-call pair.
"""

from __future__ import annotations

from typing import Callable

from . import system_prompt
from .brain import BrainChain

HISTORY_LIMIT = 40


class Agent:
    def __init__(
        self,
        chain: BrainChain,
        registry,
        on_status: Callable[[str], None] | None = None,
        max_tool_iterations: int = 8,
        max_tokens_per_turn: int = 100_000,
    ):
        self.chain = chain
        self.registry = registry
        self.on_status = on_status or (lambda status: None)
        self.max_tool_iterations = max(1, int(max_tool_iterations))
        self.max_tokens_per_turn = max(1000, int(max_tokens_per_turn))
        self.messages: list[dict] = [{"role": "system", "content": system_prompt.build()}]

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": system_prompt.build()}]

    def run_turn(self, user_text: str | list, on_text_delta: Callable[[str], None] | None = None) -> str:
        """user_text is plain text, or a list of multimodal content parts
        (e.g. text + screenshot from Mark III); both land as the user turn.
        With on_text_delta set, replies stream token-by-token to it."""
        self.messages.append({"role": "user", "content": user_text})
        tokens_used = 0
        for _ in range(self.max_tool_iterations):
            if on_text_delta is not None:
                resp = self.chain.create_chat_stream(
                    messages=self._trimmed(),
                    tools=self.registry.schemas,
                    tool_choice="auto",
                    on_text_delta=on_text_delta,
                )
            else:
                resp = self.chain.create_chat(
                    messages=self._trimmed(),
                    tools=self.registry.schemas,
                    tool_choice="auto",
                )
            usage = getattr(resp, "usage", None)
            tokens_used += getattr(usage, "total_tokens", 0) or 0
            if tokens_used > self.max_tokens_per_turn:
                self.on_status(f"token budget reached ({tokens_used} tokens)")
                return (
                    f"ERROR: per-turn token budget exhausted "
                    f"({tokens_used:,} > {self.max_tokens_per_turn:,}) - stopping this turn."
                )
            message = resp.choices[0].message
            tool_calls = message.tool_calls or []
            if not tool_calls:
                content = message.content or "(no response)"
                self.messages.append({"role": "assistant", "content": content})
                return content
            self.messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [tc.model_dump() for tc in tool_calls],
                }
            )
            for call in tool_calls:
                self.on_status(f"tool: {call.function.name}")
                result = self.registry.dispatch(call.function.name, call.function.arguments)
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )
        return (
            f"ERROR: tool budget exhausted "
            f"({self.max_tool_iterations} iterations) - stopping this turn."
        )

    def _trimmed(self) -> list[dict]:
        msgs = self.messages
        if len(msgs) <= HISTORY_LIMIT:
            return msgs
        start = len(msgs) - HISTORY_LIMIT + 1
        while start < len(msgs) and msgs[start].get("role") == "tool":
            start -= 1  # keep tool results with the assistant message that requested them
        return [msgs[0]] + msgs[start:]
