"""Probe local Ollama for `/health` llm.reachable."""

from __future__ import annotations

import httpx


async def ollama_reachable(base_url: str) -> bool:
    base = base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{base}/api/tags")
            return r.status_code == 200
    except (httpx.HTTPError, OSError):
        return False
