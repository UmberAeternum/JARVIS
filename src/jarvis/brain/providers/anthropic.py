"""Brain v2 - the Anthropic adapter: stdlib http.client to /v1/messages.

No SDK and no third-party dependency: the transport is http.client
(HTTPS) against https://api.anthropic.com/v1/messages. The API key is
read from the ANTHROPIC_API_KEY environment variable at request time and
is used only inside request headers - it is never logged, never
serialized into a payload, and never included in an error message.

The transport is injectable so tests can mock HTTP without touching the
network: transport(method, host, path, body_bytes|None, headers) ->
(status:int, bytes). OpenAI-format image attachments (see
vision.build_vision_message) are converted to Anthropic image content
blocks, so the adapter reports vision capability itself; tool support is
still the model manifest's business.
"""

from __future__ import annotations

import http.client
import json
import os
from urllib.parse import urlparse

from .base import Provider

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-sonnet-5-5"
API_VERSION = "2023-06-01"

# Media types the Messages API accepts for base64 image sources.
IMAGE_MEDIA_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


def _image_block_from_url(url: str) -> dict | None:
    """OpenAI vision part -> Anthropic image block (None when not convertible).

    UMBRA's OpenAI-format image attachments look like
    ``data:image/jpeg;base64,<payload>`` (see vision.build_vision_message).
    Those become a base64 source block. Remote http(s) URLs become a url
    source block, which the Messages API also accepts. Anything else is not
    convertible; the caller falls back to a text note.
    """
    if url.startswith("data:"):
        header, _, payload = url.partition(",")
        media_type = header[5:].split(";", 1)[0].strip().lower()
        if media_type == "image/jpg":  # common nonstandard alias
            media_type = "image/jpeg"
        if media_type not in IMAGE_MEDIA_TYPES or not payload:
            return None
        return {"type": "image",
                "source": {"type": "base64", "media_type": media_type,
                           "data": payload}}
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _default_transport(method: str, host: str, path: str, body: bytes | None,
                       headers: dict) -> tuple[int, bytes]:
    conn = http.client.HTTPSConnection(host, timeout=30)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str = DEFAULT_MODEL,
                 base_url: str = DEFAULT_BASE_URL,
                 max_tokens: int = 1024, timeout: int = 30, transport=None):
        parsed = urlparse(base_url if "://" in base_url
                          else f"https://{base_url}")
        self.host = parsed.hostname or "api.anthropic.com"
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._transport = transport or _default_transport

    # ------------------------------------------------------------- transport

    def _headers(self, with_body: bool) -> dict:
        """Request headers. The key goes here and ONLY here; it is read
        from the environment per call and never stored on the instance."""
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set - the anthropic provider "
                "needs it to talk to api.anthropic.com")
        headers = {"anthropic-version": API_VERSION}
        if with_body:
            headers["Content-Type"] = "application/json"
        headers["x-api-key"] = key
        return headers

    def _request(self, method: str, path: str, body: dict | None) -> dict:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        status, raw = self._transport(method, self.host, path, payload,
                                      self._headers(payload is not None))
        data = json.loads(raw.decode("utf-8"))
        if status != 200:
            # error bodies may echo request metadata - never the headers
            raise RuntimeError(f"anthropic {path} -> HTTP {status}: {data}")
        return data

    # ------------------------------------------------------------- mapping

    @staticmethod
    def _tool_use_blocks(tool_calls) -> list[dict]:
        """OpenAI-ish assistant tool_calls -> Anthropic tool_use blocks."""
        blocks: list[dict] = []
        for i, call in enumerate(tool_calls or []):
            fn = call.get("function", call) if isinstance(call, dict) else {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
                if not isinstance(args, dict):
                    args = {}
            except ValueError:
                args = {}
            blocks.append({
                "type": "tool_use",
                "id": str(call.get("id", f"call_{i}")) if isinstance(call, dict) else f"call_{i}",
                "name": str(fn.get("name", "")),
                "input": args,
            })
        return blocks

    @staticmethod
    def _tool_schema(tool: dict) -> dict:
        """Accept both OpenAI-style (function-wrapped) and flat schemas."""
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        return {
            "name": str(fn.get("name", "")),
            "description": str(fn.get("description", "")),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        }

    def _to_anthropic(self, messages: list[dict],
                      tools: list[dict] | None) -> dict:
        """Map the common OpenAI-ish message list onto the Messages API:
        system messages lift to the top-level 'system' field, tool results
        become user tool_result blocks, assistant tool_calls become
        tool_use blocks."""
        system_parts: list[str] = []
        out: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                if content:
                    system_parts.append(str(content))
                continue
            if role == "tool":
                out.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": str(msg.get("tool_call_id", "")),
                    "content": str(content or ""),
                }]})
                continue
            if role == "assistant" and msg.get("tool_calls"):
                blocks: list[dict] = []
                if content:
                    blocks.append({"type": "text", "text": str(content)})
                blocks.extend(self._tool_use_blocks(msg.get("tool_calls")))
                out.append({"role": "assistant", "content": blocks})
                continue
            if isinstance(content, list):
                # OpenAI multimodal format: text and image_url parts.
                blocks: list[dict] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url = str((part.get("image_url") or {}).get("url", ""))
                        block = _image_block_from_url(url)
                        if block is not None:
                            blocks.append(block)
                        else:
                            blocks.append({"type": "text",
                                           "text": "[image attachment omitted: "
                                                   "unsupported format]"})
                        continue
                    text = part.get("text", "") if isinstance(part, dict) else part
                    if str(text):
                        blocks.append({"type": "text", "text": str(text)})
                if blocks:
                    out.append({"role": "assistant" if role == "assistant" else "user",
                                "content": blocks})
                continue
            out.append({"role": "assistant" if role == "assistant" else "user",
                        "content": str(content or "")})
        payload: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": out,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = [self._tool_schema(tool) for tool in tools]
        return payload

    # ------------------------------------------------------------ interface

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        data = self._request("POST", "/v1/messages",
                             self._to_anthropic(messages, tools))
        blocks = data.get("content") or []
        reply = "".join(
            block.get("text", "") for block in blocks
            if isinstance(block, dict) and block.get("type") == "text")
        tool_calls = [
            {"id": block.get("id"), "name": str(block.get("name", "")),
             "arguments": json.dumps(block.get("input") or {})}
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        return {"reply": reply, "tool_calls": tool_calls or None}

    def tools(self) -> list[str]:
        # The Messages API has no server-side tool catalog; capability is
        # the manifest's business, not the adapter's. Kept honest: [].
        return []

    def vision(self) -> bool:
        return True  # OpenAI-format image attachments are converted to image blocks

    def embed(self, text: str) -> list[float] | None:
        return None  # the Messages API has no embeddings endpoint

    def health(self) -> dict:
        """Cheap free probe: GET /v1/models (no tokens billed). Without a
        configured key the answer is honest and local - no network call,
        and no hint of a key value in the detail."""
        if not os.environ.get("ANTHROPIC_API_KEY", ""):
            return {"ok": False, "detail": "ANTHROPIC_API_KEY not set"}
        try:
            status, _raw = self._transport("GET", self.host,
                                           "/v1/models?limit=1", None,
                                           self._headers(with_body=False))
            if status == 200:
                return {"ok": True, "detail": "api.anthropic.com reachable"}
            return {"ok": False, "detail": f"/v1/models -> HTTP {status}"}
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}
