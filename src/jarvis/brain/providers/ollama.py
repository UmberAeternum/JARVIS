"""Brain v0 - the Ollama adapter (native /api surface, loopback).

The transport is injectable so tests can mock HTTP without touching the
network: transport(method, path, body_bytes|None) -> (status:int, bytes).
The real transport speaks http.client to the Ollama host (default
127.0.0.1:11434 - local by design).
"""

from __future__ import annotations

import http.client
import json
from urllib.parse import urlparse

from .base import Provider


def _default_transport(method: str, host: str, port: int, path: str,
                       body: bytes | None) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=30)
    try:
        conn.request(method, path, body=body,
                     headers={"Content-Type": "application/json"} if body else {})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "qwen2.5:7b", transport=None):
        parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 11434
        self.model = model
        self._transport = transport or _default_transport

    def _call(self, path: str, body: dict | None = None) -> dict:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        status, raw = self._transport("POST" if body is not None else "GET",
                                      self.host, self.port, path, payload)
        data = json.loads(raw.decode("utf-8"))
        if status != 200:
            raise RuntimeError(f"ollama {path} -> HTTP {status}: {data}")
        return data

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        body: dict = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            body["tools"] = tools
        data = self._call("/api/chat", body)
        message = (data.get("message") or {})
        return {
            "reply": str(message.get("content", "")),
            "tool_calls": message.get("tool_calls") or None,
        }

    def tools(self) -> list[str]:
        # Ollama itself has no server-side tool list; capability comes from
        # the model manifest. Kept honest: unknown -> [].
        return []

    def vision(self) -> bool:
        return False  # decided by the manifest, not the adapter

    def embed(self, text: str) -> list[float] | None:
        try:
            data = self._call("/api/embeddings",
                              {"model": self.model, "prompt": text})
            return data.get("embedding") or None
        except Exception:
            return None

    def health(self) -> dict:
        try:
            data = self._call("/api/tags")
            models = [m.get("name", "") for m in data.get("models", [])]
            return {"ok": True, "detail": f"models: {', '.join(models) or '(none)'}",
                    "models": models}
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}
