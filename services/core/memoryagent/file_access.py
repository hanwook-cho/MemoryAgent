"""Allowlisted paths for tool reads (under data dir or watched roots)."""

from __future__ import annotations

from pathlib import Path


def path_is_allowlisted_for_read(path: Path, *, data_dir: Path, watched_roots: list[str]) -> bool:
    """True if resolved path is under `data_dir` or under any existing watched root."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    data_resolved = data_dir.resolve()
    try:
        resolved.relative_to(data_resolved)
        return True
    except ValueError:
        pass
    for raw in watched_roots:
        root = Path(raw).expanduser()
        try:
            root_r = root.resolve()
        except OSError:
            continue
        if not root_r.exists():
            continue
        try:
            resolved.relative_to(root_r)
            return True
        except ValueError:
            continue
    return False
