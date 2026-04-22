"""Data directory layout (see docs/spec/data-model.md)."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Repository root (contains `services/`, `web/`)."""
    # memoryagent/paths.py -> parents[2] = services/core, [3] = repo
    return Path(__file__).resolve().parents[3]


def default_data_dir() -> Path:
    """Override with MEMORYAGENT_DATA_DIR; default `.memoryagent` in CWD."""
    return Path(os.environ.get("MEMORYAGENT_DATA_DIR", ".memoryagent")).resolve()


def web_dist() -> Path:
    """Built web assets (`web/dist`)."""
    return repo_root() / "web" / "dist"
