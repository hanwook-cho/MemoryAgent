"""Deployment mode helpers for runtime status (MP1 PR-2 + edge URL / health)."""

from __future__ import annotations

from typing import Any


def _edge_url_norm(raw: str | None) -> str | None:
    s = (raw or "").strip()
    return s or None


def deployment_degraded_tuple(
    deployment_mode: str,
    *,
    edge_base_url: str | None,
    edge_reachable: bool | None,
    edge_error: str | None,
) -> tuple[bool, str | None]:
    """
    Returns ``(degraded, degraded_reason)`` for health and chat ``meta``.

    ``edge_reachable``:
    - ``None`` — no ping attempted (standalone, or no ``edge_base_url``).
    - ``True`` / ``False`` — result of :func:`memoryagent.node_client.fetch_edge_health`.
    """
    if deployment_mode == "standalone":
        return False, None
    edge = _edge_url_norm(edge_base_url)
    if not edge:
        return (
            True,
            "deployment_mode is not standalone but edge_base_url is not set; "
            "set edge_base_url to your Edge Node base URL.",
        )
    if edge_reachable is True:
        return False, None
    if edge_reachable is False:
        msg = edge_error or "Edge node did not respond OK to GET /health."
        return True, msg
    return (
        True,
        "Edge reachability has not been checked (unexpected); treating as degraded.",
    )


def health_deployment_block(
    deployment_mode: str,
    *,
    edge_base_url: str | None = None,
    edge_reachable: bool | None = None,
    edge_error: str | None = None,
) -> dict[str, Any]:
    """
    ``GET /health`` fragment: mode + whether distributed features are degraded.

    When ``edge_base_url`` is set and ``GET /health`` on the edge succeeds,
    ``degraded`` is ``False`` (remote is up; host still uses local backends until
    remote retrieval/ingest adapters are wired).
    """
    degraded, reason = deployment_degraded_tuple(
        deployment_mode,
        edge_base_url=edge_base_url,
        edge_reachable=edge_reachable,
        edge_error=edge_error,
    )
    edge = _edge_url_norm(edge_base_url)
    out: dict[str, Any] = {
        "mode": deployment_mode,
        "degraded": degraded,
        "degraded_reason": reason,
        "edge_base_url": edge,
    }
    if deployment_mode != "standalone" and edge:
        out["edge_reachable"] = bool(edge_reachable) if edge_reachable is not None else None
    return out


def chat_meta_block(
    deployment_mode: str,
    *,
    edge_base_url: str | None,
    edge_reachable: bool | None,
    edge_error: str | None,
) -> dict[str, Any]:
    """``meta`` object for ``POST /chat`` / stream (MP1)."""
    degraded, reason = deployment_degraded_tuple(
        deployment_mode,
        edge_base_url=edge_base_url,
        edge_reachable=edge_reachable,
        edge_error=edge_error,
    )
    return {"degraded": degraded, "degraded_reason": reason}
