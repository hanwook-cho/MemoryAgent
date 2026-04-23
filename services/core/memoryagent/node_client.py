"""HTTP stub client for Edge Node (MP1): health check only until retrieve/ingest are wired."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_edge_health(
    base_url: str,
    *,
    bearer_token: str,
    timeout_seconds: float = 3.0,
) -> tuple[bool, str | None]:
    """
    ``GET {base}/health`` per Node API §5.1 (``docs/spec/node-api.md``).

    Returns ``(True, None)`` on HTTP 200, else ``(False, message)``.
    """
    root = base_url.rstrip("/")
    url = f"{root}/health"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            r = await client.get(
                url,
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
    except (httpx.HTTPError, OSError, ValueError) as e:
        logger.warning("edge health request failed url=%s err=%s", url, e)
        return False, str(e) or "edge unreachable"
    if r.status_code == 200:
        return True, None
    return False, f"edge health HTTP {r.status_code}"
