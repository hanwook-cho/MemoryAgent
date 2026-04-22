"""Chat completion via Ollama or injectable fakes for tests."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx

from memoryagent.schemas import ChatMessage


@runtime_checkable
class LlmClient(Protocol):
    async def chat(self, messages: list[ChatMessage], *, context_blocks: list[str]) -> str: ...


class OllamaLlm:
    def __init__(self, base_url: str, model: str) -> None:
        self._base = base_url.rstrip("/")
        self._model = model

    async def chat(self, messages: list[ChatMessage], *, context_blocks: list[str]) -> str:
        sys_parts = [
            "You are MemoryAgent, a private on-device assistant.",
            "Use the memory context below when it helps answer the user.",
            "",
            "Memory context:",
            "\n---\n".join(context_blocks) if context_blocks else "(none)",
        ]
        ollama_messages: list[dict[str, str]] = [
            {"role": "system", "content": "\n".join(sys_parts)},
        ]
        for m in messages:
            ollama_messages.append({"role": m.role, "content": m.content})

        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(
                f"{self._base}/api/chat",
                json={
                    "model": self._model,
                    "messages": ollama_messages,
                    "stream": False,
                },
            )
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            msg = data.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, str):
                raise RuntimeError("invalid chat response")
            return content


class FakeLlm:
    """Returns a fixed reply; tests assert on citations from RAG, not this text."""

    def __init__(self, reply: str = "ok") -> None:
        self._reply = reply

    async def chat(self, messages: list[ChatMessage], *, context_blocks: list[str]) -> str:
        _ = messages, context_blocks
        return self._reply
