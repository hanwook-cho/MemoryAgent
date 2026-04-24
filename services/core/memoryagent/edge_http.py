"""Shared TLS / httpx ``verify`` settings for Host → Edge HTTP clients (MP1)."""

from __future__ import annotations

import logging
from pathlib import Path

from memoryagent.config_store import AppConfig

logger = logging.getLogger(__name__)


def edge_httpx_verify(cfg: AppConfig) -> bool | str:
    """
    Return ``httpx`` ``verify`` argument for edge requests.

    - ``edge_tls_insecure_skip_verify``: disable verification (dev only; logs warning).
    - ``edge_tls_ca_bundle``: path to PEM CA bundle when set and the file exists.
    - Otherwise: ``True`` (system / default trust store).
    """
    if getattr(cfg, "edge_tls_insecure_skip_verify", False):
        logger.warning(
            "edge_tls_insecure_skip_verify is true; TLS certificate verification is disabled for edge"
        )
        return False
    raw = getattr(cfg, "edge_tls_ca_bundle", None)
    if raw:
        p = Path(str(raw)).expanduser()
        if p.is_file():
            return str(p.resolve())
        logger.warning("edge_tls_ca_bundle is not a readable file (%s); using default verify", raw)
    return True


def edge_mapped_file_ingest_path(
    host_path: Path,
    *,
    host_root: Path | None,
    edge_root: str | None,
) -> str | None:
    """
    Map a host-resolved file path to a Node-local path for ``POST /ingest`` ``kind=file``.

    Both ``host_root`` and ``edge_root`` must be set; otherwise returns ``None``.
    """
    if host_root is None or not edge_root or not str(edge_root).strip():
        return None
    try:
        rel = host_path.expanduser().resolve().relative_to(host_root)
    except ValueError:
        return None
    er = str(edge_root).strip().rstrip("/")
    return f"{er}/{rel.as_posix()}"


def resolved_edge_path_host_root(cfg: AppConfig) -> Path | None:
    """Return resolved directory prefix for host-side path mapping, or ``None``."""
    raw = getattr(cfg, "edge_ingest_path_host_prefix", None)
    if not raw or not str(raw).strip():
        return None
    p = Path(str(raw)).expanduser()
    try:
        return p.resolve()
    except OSError:
        logger.warning("edge_ingest_path_host_prefix could not be resolved: %s", raw)
        return None
