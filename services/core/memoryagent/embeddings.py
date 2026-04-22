"""Text → embedding vectors (Ollama or deterministic test stub)."""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Protocol, runtime_checkable

import httpx


def deterministic_embedding(text: str, dim: int = 384) -> list[float]:
    """Reproducible unit-norm vector for tests (no network)."""
    out: list[float] = []
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    i = 0
    while len(out) < dim:
        block = hashlib.sha256(seed + str(i).encode()).digest()
        for j in range(0, 32, 2):
            if len(out) >= dim:
                break
            v = int.from_bytes(block[j : j + 2], "big") / 65535.0 * 2.0 - 1.0
            out.append(v)
        i += 1
    norm = math.sqrt(sum(x * x for x in out)) or 1.0
    return [x / norm for x in out]


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str) -> None:
        self._base = base_url.rstrip("/")
        self._model = model

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{self._base}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            r.raise_for_status()
            data = r.json()
            emb = data.get("embedding")
            if not isinstance(emb, list):
                raise RuntimeError("invalid embedding response")
            return [float(x) for x in emb]


class DeterministicEmbedder:
    """Delegates to :func:`deterministic_embedding`."""

    async def embed(self, text: str) -> list[float]:
        return deterministic_embedding(text)
