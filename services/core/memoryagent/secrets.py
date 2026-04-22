"""Bearer token under `secrets/` (see docs/spec/http-api.md)."""

from __future__ import annotations

import secrets as py_secrets
from pathlib import Path


def bearer_token_path(data_dir: Path) -> Path:
    return data_dir / "secrets" / "bearer.token"


def load_or_create_bearer_token(data_dir: Path) -> str:
    path = bearer_token_path(data_dir)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = py_secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    return token
