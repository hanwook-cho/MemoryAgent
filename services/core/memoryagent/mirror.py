"""Markdown mirror files (`mirror/SOUL.md`, `mirror/USER.md`) — see docs/spec/data-model.md §4."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

MIRROR_FILES: dict[str, str] = {
    "user": "USER.md",
    "soul": "SOUL.md",
}


def mirror_dir(data_dir: Path) -> Path:
    return data_dir / "mirror"


def mirror_path(data_dir: Path, mirror_id: str) -> Path:
    if mirror_id not in MIRROR_FILES:
        raise KeyError(mirror_id)
    return mirror_dir(data_dir) / MIRROR_FILES[mirror_id]


def parse_mirror_file(text: str) -> tuple[dict[str, Any], str]:
    """Split optional YAML front matter from Markdown body. Body is what gets embedded."""
    if not text:
        return {}, ""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("Unclosed YAML front matter (missing closing ---).")
    fm_raw = "".join(lines[1:end])
    body = "".join(lines[end + 1 :])
    try:
        loaded = yaml.safe_load(fm_raw)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in front matter: {e}") from e
    if loaded is None:
        fm: dict[str, Any] = {}
    elif not isinstance(loaded, dict):
        raise ValueError("YAML front matter must be a mapping (object).")
    else:
        fm = loaded
    return fm, body


def validate_mirror_content(text: str) -> None:
    """Raise ValueError with a human message if the file is invalid."""
    parse_mirror_file(text)


def _default_front_matter(mirror_id: str, file_uri: str) -> str:
    import uuid

    doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, file_uri))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    title = "User memory" if mirror_id == "user" else "Soul / identity"
    return (
        f"---\n"
        f'id: "{doc_id}"\n'
        f'updated_at: "{now}"\n'
        f"tags: []\n"
        f'mirror: "{mirror_id}"\n'
        f'title: "{title}"\n'
        f"---\n\n"
    )


def default_mirror_body(mirror_id: str) -> str:
    if mirror_id == "user":
        return (
            "# USER memory\n\n"
            "Add durable preferences and facts you want retrieval to use. "
            "**Only the Markdown below the front matter** is embedded for search.\n"
        )
    return (
        "# SOUL / identity\n\n"
        "Describe tone, boundaries, and long-lived context for the assistant. "
        "**Only the Markdown below the front matter** is embedded for search.\n"
    )


def ensure_mirror_file(data_dir: Path, mirror_id: str) -> Path:
    """Create `mirror/` and the file with defaults if missing."""
    mdir = mirror_dir(data_dir)
    mdir.mkdir(parents=True, exist_ok=True)
    path = mirror_path(data_dir, mirror_id)
    if not path.is_file():
        uri = path.resolve().as_uri()
        path.write_text(
            _default_front_matter(mirror_id, uri) + default_mirror_body(mirror_id),
            encoding="utf-8",
        )
    return path
