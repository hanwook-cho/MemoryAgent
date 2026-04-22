"""Logging configuration for MemoryAgent core (M5 hardening)."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(data_dir: Path, *, force: bool = False) -> None:
    """
    Configure root logging:
    - console handler (INFO)
    - rotating file handler at `<data_dir>/logs/core.log`

    Environment overrides:
    - MEMORYAGENT_LOG_MAX_BYTES (default 5_000_000)
    - MEMORYAGENT_LOG_BACKUP_COUNT (default 3)
    """
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "core.log"

    max_bytes = _int_env("MEMORYAGENT_LOG_MAX_BYTES", 5_000_000)
    backup_count = _int_env("MEMORYAGENT_LOG_BACKUP_COUNT", 3)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Remove existing managed handlers when force=True or when file target changed.
    for h in list(root.handlers):
        if not getattr(h, "_memoryagent_managed", False):
            continue
        if force:
            root.removeHandler(h)
            h.close()
            continue
        if isinstance(h, RotatingFileHandler):
            old = Path(h.baseFilename)
            if old != log_path:
                root.removeHandler(h)
                h.close()

    has_console = any(
        getattr(h, "_memoryagent_managed", False) and getattr(h, "_memoryagent_kind", "") == "console"
        for h in root.handlers
    )
    if not has_console:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        ch._memoryagent_managed = True  # type: ignore[attr-defined]
        ch._memoryagent_kind = "console"  # type: ignore[attr-defined]
        root.addHandler(ch)

    has_file = any(
        isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == log_path
        for h in root.handlers
    )
    if not has_file:
        fh = RotatingFileHandler(
            filename=str(log_path),
            maxBytes=max(1, max_bytes),
            backupCount=max(1, backup_count),
            encoding="utf-8",
        )
        fh.setLevel(logging.INFO)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        fh._memoryagent_managed = True  # type: ignore[attr-defined]
        fh._memoryagent_kind = "file"  # type: ignore[attr-defined]
        root.addHandler(fh)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
