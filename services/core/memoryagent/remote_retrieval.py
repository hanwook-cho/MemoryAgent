"""Host → Edge Node ``POST /retrieve`` (Node API §5.3)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from memoryagent.rag_service import SearchFilters
from memoryagent.schemas import SearchResultItem

logger = logging.getLogger(__name__)


def _filters_to_node_payload(
    query: str,
    limit: int,
    filters: SearchFilters | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"query": query, "limit": limit}
    if not filters:
        return body
    fd: dict[str, Any] = {}
    if filters.source_kind:
        fd["source_kind"] = filters.source_kind
    if filters.path_prefix:
        fd["path_prefix"] = filters.path_prefix
    if filters.indexed_after:
        fd["indexed_after"] = filters.indexed_after.isoformat().replace("+00:00", "Z")
    if filters.indexed_before:
        fd["indexed_before"] = filters.indexed_before.isoformat().replace("+00:00", "Z")
    if fd:
        body["filters"] = fd
    return body


def node_results_to_search_items(data: dict[str, Any]) -> list[SearchResultItem]:
    raw = data.get("results")
    if not isinstance(raw, list):
        return []
    out: list[SearchResultItem] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                SearchResultItem(
                    chunk_id=str(row.get("chunk_id", "")),
                    snippet=str(row.get("snippet", ""))[:500],
                    score=float(row.get("score", 0.0)),
                    document_id=str(row.get("document_id", "")),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


async def post_node_retrieve(
    edge_base_url: str,
    bearer_token: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """POST ``{edge}/retrieve``; raises on non-2xx or network error."""
    root = edge_base_url.rstrip("/")
    url = f"{root}/retrieve"
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {bearer_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if r.status_code != 200:
        raise RuntimeError(f"edge retrieve HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("edge retrieve returned non-object JSON")
    return data


async def try_node_retrieve(
    edge_base_url: str,
    bearer_token: str,
    query: str,
    *,
    limit: int = 20,
    filters: SearchFilters | None = None,
) -> list[SearchResultItem] | None:
    """
    Returns parsed results, or ``None`` if the request should fall back to local
    (network/HTTP/shape errors).
    """
    payload = _filters_to_node_payload(query, limit, filters)
    try:
        data = await post_node_retrieve(edge_base_url, bearer_token, payload)
    except (httpx.HTTPError, OSError, RuntimeError, ValueError, TypeError) as e:
        logger.warning("edge retrieve failed: %s", e)
        return None
    return node_results_to_search_items(data)
