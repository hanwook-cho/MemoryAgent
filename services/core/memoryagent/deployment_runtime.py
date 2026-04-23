"""Deployment mode helpers for runtime status (MP1 PR-2)."""

from __future__ import annotations

from typing import Any


def health_deployment_block(deployment_mode: str) -> dict[str, Any]:
    """
    ``GET /health`` fragment: mode + whether distributed features are degraded.

    Non-``standalone`` modes are marked degraded until remote adapters are wired.
    """
    if deployment_mode == "standalone":
        return {
            "mode": deployment_mode,
            "degraded": False,
            "degraded_reason": None,
        }
    return {
        "mode": deployment_mode,
        "degraded": True,
        "degraded_reason": (
            "Distributed deployment mode is active but remote "
            "retrieval/ingest is not configured in this build."
        ),
    }
