"""Host → Edge Node ``POST /ingest`` (Node API §5.4) — memory fan-out."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def try_node_ingest_memory(
    edge_base_url: str,
    bearer_token: str,
    *,
    text: str,
    tags: list[str],
    source: str,
    timeout_seconds: float = 30.0,
    verify: bool | str = True,
) -> bool:
    """
    POST ``{edge}/ingest`` with ``kind: memory``.

    Returns ``True`` on HTTP 200/202, ``False`` on any failure (caller may ignore).
    """
    root = edge_base_url.rstrip("/")
    url = f"{root}/ingest"
    payload: dict[str, Any] = {
        "kind": "memory",
        "text": text,
        "tags": list(tags),
        "source": source,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, verify=verify) as client:
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except (httpx.HTTPError, OSError, ValueError) as e:
        logger.warning("edge ingest memory failed: %s", e)
        return False
    if r.status_code in (200, 202):
        return True
    logger.warning("edge ingest memory HTTP %s: %s", r.status_code, r.text[:200])
    return False


async def try_node_ingest_file(
    edge_base_url: str,
    bearer_token: str,
    *,
    path: str,
    timeout_seconds: float = 120.0,
    verify: bool | str = True,
    force_reindex: bool = False,
) -> bool:
    """
    POST ``{edge}/ingest`` with ``kind: file`` and Node-local ``path`` (Node API §5.4).

    Returns ``True`` on HTTP 200/202, ``False`` on any failure (caller may ignore).
    """
    root = edge_base_url.rstrip("/")
    url = f"{root}/ingest"
    payload: dict[str, Any] = {
        "kind": "file",
        "path": path,
        "options": {"force_reindex": force_reindex},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, verify=verify) as client:
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except (httpx.HTTPError, OSError, ValueError) as e:
        logger.warning("edge ingest file failed: %s", e)
        return False
    if r.status_code in (200, 202):
        return True
    logger.warning("edge ingest file HTTP %s: %s", r.status_code, r.text[:200])
    return False
